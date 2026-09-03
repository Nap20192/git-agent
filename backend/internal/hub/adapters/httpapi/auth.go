package httpapi

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log/slog"
	"net/http"

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
}

func (s *Session) Wrap(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		userID, ok := s.currentUser(r)
		if !ok {
			http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
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
		slog.Error("auth: session lookup failed", "err", err)
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
}

// redirectURI строится из запроса: провайдеру регистрируют точный callback,
// в dev это localhost/туннель — держим схему и хост входящего запроса.
func redirectURI(r *http.Request, provider string) string {
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
		http.Error(w, `{"error":"unknown provider"}`, http.StatusBadRequest)
		return
	}
	stateBytes := make([]byte, 16)
	if _, err := rand.Read(stateBytes); err != nil {
		writeError(w, err)
		return
	}
	state := hex.EncodeToString(stateBytes)

	authURL, err := h.Service.LoginURL(provider, redirectURI(r, provider), state)
	if err != nil {
		writeError(w, err)
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name: stateCookie, Value: state, Path: "/api/auth",
		MaxAge: 600, HttpOnly: true, SameSite: http.SameSiteLaxMode,
	})
	http.Redirect(w, r, authURL, http.StatusFound)
}

// Callback — GET /api/auth/{provider}/callback: state-проверка (anti-CSRF),
// вход либо добавление связки (живая сессия), cookie сессии, redirect на фронт.
func (h *AuthHandler) Callback(w http.ResponseWriter, r *http.Request) {
	provider := r.PathValue("provider")
	code := r.URL.Query().Get("code")
	state := r.URL.Query().Get("state")
	stateC, err := r.Cookie(stateCookie)
	if code == "" || state == "" || err != nil || stateC.Value != state {
		http.Error(w, `{"error":"invalid oauth state"}`, http.StatusBadRequest)
		return
	}
	http.SetCookie(w, &http.Cookie{Name: stateCookie, Path: "/api/auth", MaxAge: -1})

	var currentUser *int64
	if id, ok := h.Session.currentUser(r); ok {
		currentUser = &id // живая сессия ⇒ добавление связки, не вход
	}
	token, expires, err := h.Service.HandleCallback(r.Context(), provider, code, redirectURI(r, provider), currentUser)
	if err != nil {
		slog.Error("auth: oauth callback failed", "provider", provider, "err", err)
		writeError(w, err)
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name: sessionCookie, Value: token, Path: "/",
		Expires: expires, HttpOnly: true, SameSite: http.SameSiteLaxMode,
	})
	http.Redirect(w, r, h.FrontendURL, http.StatusFound)
}

// Logout — POST /api/auth/logout: сессия удаляется, cookie гасится.
func (h *AuthHandler) Logout(w http.ResponseWriter, r *http.Request) {
	if c, err := r.Cookie(sessionCookie); err == nil && c.Value != "" {
		if err := h.Service.Logout(r.Context(), c.Value); err != nil {
			writeError(w, err)
			return
		}
	}
	http.SetCookie(w, &http.Cookie{Name: sessionCookie, Path: "/", MaxAge: -1, HttpOnly: true})
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
		writeError(w, err)
		return
	}
	idents, err := h.Identities.Identities(r.Context(), uid)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, meDTO{ID: uid, DisplayName: name, Identities: mapSlice(idents, toIdentityDTO)})
}
