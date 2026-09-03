package httpapi

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log/slog"
	"net/http"
	"strings"

	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

const (
	sessionCookie = "hub_session"
	stateCookie   = "hub_oauth_state"
)

type ctxKey int

const userIDKey ctxKey = 0

// Session — auth-middleware пользовательских роутов (тикет 003):
// opaque-токен из httpOnly cookie против hub.sessions; нет/истёк — 401.
type Session struct {
	Store domain.AuthStore
	// DevUserID — dev-обход OAuth (DEV_USER_ID в .env): без валидной cookie
	// запрос идёт от этого пользователя. 0 = выключено (прод).
	DevUserID int64
}

func (s *Session) Wrap(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		userID, ok := s.currentUser(r)
		if !ok && s.DevUserID != 0 {
			userID, ok = s.DevUserID, true
		}
		if !ok {
			errorJSON(w, http.StatusUnauthorized, "unauthorized")
			return
		}
		next(w, r.WithContext(context.WithValue(r.Context(), userIDKey, userID)))
	}
}

// currentUser — пользователь живой сессии; ok=false без валидной cookie.
func (s *Session) currentUser(r *http.Request) (int64, bool) {
	c, err := r.Cookie(sessionCookie)
	if err != nil || c.Value == "" {
		return 0, false
	}
	userID, ok, err := s.Store.SessionUser(r.Context(), c.Value)
	if err != nil {
		slog.ErrorContext(r.Context(), "auth: session lookup failed", "err", err)
		return 0, false
	}
	return userID, ok
}

func userID(r *http.Request) int64 {
	id, _ := r.Context().Value(userIDKey).(int64)
	return id
}

// AuthHandler — OAuth-вход (модель Railway): login-redirect, callback,
// logout, /api/me.
type AuthHandler struct {
	Service     *app.AuthService
	Session     *Session
	Store       domain.AuthStore
	Identities  domain.IdentityStore
	FrontendURL string
	// PublicBaseURL — публичный базовый URL (WEBHOOK_BASE_URL), под которым hub
	// доступен провайдеру. Callback у провайдера зарегистрирован на него, а не
	// на localhost, поэтому redirect_uri берём отсюда. Пусто — из запроса.
	PublicBaseURL string
}

// redirectURI: callback у провайдера зарегистрирован на PublicBaseURL (туннель),
// поэтому redirect_uri в login и обмене кода должны совпадать именно с ним.
// Без PublicBaseURL — схема+хост входящего запроса (например, прямой localhost).
func (h *AuthHandler) redirectURI(r *http.Request, provider string) string {
	if h.PublicBaseURL != "" {
		return fmt.Sprintf("%s/api/auth/%s/callback", strings.TrimRight(h.PublicBaseURL, "/"), provider)
	}
	scheme := "http"
	if r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https" {
		scheme = "https"
	}
	return fmt.Sprintf("%s://%s/api/auth/%s/callback", scheme, r.Host, provider)
}

// Login — GET /api/auth/{provider}/login: redirect на OAuth провайдера.
func (h *AuthHandler) Login(w http.ResponseWriter, r *http.Request) {
	provider := r.PathValue("provider")
	if provider != "github" && provider != "gitlab" {
		errorJSON(w, http.StatusBadRequest, "unknown provider")
		return
	}
	stateBytes := make([]byte, 16)
	if _, err := rand.Read(stateBytes); err != nil {
		writeError(w, r, err)
		return
	}
	state := hex.EncodeToString(stateBytes)

	authURL, err := h.Service.LoginURL(provider, h.redirectURI(r, provider), state)
	if err != nil {
		writeError(w, r, err)
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name: stateCookie, Value: state, Path: "/api/auth",
		MaxAge: 600, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode,
	})
	http.Redirect(w, r, authURL, http.StatusFound) //nolint:gosec // URL провайдера из конфига, не из запроса
}

// Callback — GET /api/auth/{provider}/callback: state-проверка (anti-CSRF),
// вход либо добавление связки (живая сессия), cookie сессии, redirect на фронт.
func (h *AuthHandler) Callback(w http.ResponseWriter, r *http.Request) {
	provider := r.PathValue("provider")
	code := r.URL.Query().Get("code")
	state := r.URL.Query().Get("state")
	stateC, err := r.Cookie(stateCookie)
	if code == "" || state == "" || err != nil || stateC.Value != state {
		errorJSON(w, http.StatusBadRequest, "invalid oauth state")
		return
	}
	http.SetCookie(w, &http.Cookie{Name: stateCookie, Path: "/api/auth", MaxAge: -1, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode})

	var currentUser *int64
	if id, ok := h.Session.currentUser(r); ok {
		currentUser = &id // живая сессия ⇒ добавление связки, не вход
	}
	token, expires, err := h.Service.HandleCallback(r.Context(), provider, code, h.redirectURI(r, provider), currentUser)
	if err != nil {
		writeError(w, r, fmt.Errorf("oauth callback %s: %w", provider, err))
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name: sessionCookie, Value: token, Path: "/",
		Expires: expires, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode,
	})
	http.Redirect(w, r, h.FrontendURL, http.StatusFound)
}

// Logout — POST /api/auth/logout: сессия удаляется, cookie гасится.
func (h *AuthHandler) Logout(w http.ResponseWriter, r *http.Request) {
	if c, err := r.Cookie(sessionCookie); err == nil && c.Value != "" {
		if err := h.Service.Logout(r.Context(), c.Value); err != nil {
			writeError(w, r, err)
			return
		}
	}
	http.SetCookie(w, &http.Cookie{Name: sessionCookie, Path: "/", MaxAge: -1, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode})
	w.WriteHeader(http.StatusNoContent)
}

type meDTO struct {
	ID          int64         `json:"id"`
	DisplayName string        `json:"displayName"`
	Identities  []identityDTO `json:"identities"`
}

// Me — GET /api/me: пользователь со связками, БЕЗ токенов (за Session).
func (h *AuthHandler) Me(w http.ResponseWriter, r *http.Request) {
	uid := userID(r)
	name, err := h.Store.UserDisplayName(r.Context(), uid)
	if err != nil {
		writeError(w, r, err)
		return
	}
	idents, err := h.Identities.Identities(r.Context(), uid)
	if err != nil {
		writeError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, meDTO{ID: uid, DisplayName: name, Identities: mapSlice(idents, toIdentityDTO)})
}
