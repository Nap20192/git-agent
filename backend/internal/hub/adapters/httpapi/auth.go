package httpapi

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"net/http"
	"strings"

	"go.uber.org/zap"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// OAuth-вход по модели Railway (тикет 003).

func (s *Server) redirectURI(r *http.Request, provider string) string {
	if s.PublicBaseURL != "" {
		return fmt.Sprintf("%s/api/auth/%s/callback", strings.TrimRight(s.PublicBaseURL, "/"), provider)
	}
	scheme := "http"
	if r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https" {
		scheme = "https"
	}
	return fmt.Sprintf("%s://%s/api/auth/%s/callback", scheme, r.Host, provider)
}

// GET /api/auth/{provider}/login.
func (s *Server) login(w http.ResponseWriter, r *http.Request) error {
	provider := r.PathValue("provider")
	if provider != "github" && provider != "gitlab" {
		return domain.Invalid("unknown provider")
	}
	stateBytes := make([]byte, 16)
	if _, err := rand.Read(stateBytes); err != nil {
		return err
	}
	state := hex.EncodeToString(stateBytes)
	authURL, err := s.Auth.LoginURL(provider, s.redirectURI(r, provider), state)
	if err != nil {
		return err
	}
	http.SetCookie(w, &http.Cookie{
		Name: stateCookie, Value: state, Path: "/api/auth",
		MaxAge: 600, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode,
	})
	http.Redirect(w, r, authURL, http.StatusFound)
	return nil
}

// GET /api/auth/{provider}/callback.
func (s *Server) callback(w http.ResponseWriter, r *http.Request) error {
	provider := r.PathValue("provider")
	code := r.URL.Query().Get("code")
	state := r.URL.Query().Get("state")
	stateC, err := r.Cookie(stateCookie)
	if code == "" || state == "" || err != nil || stateC.Value != state {
		return domain.Invalid("invalid oauth state")
	}
	http.SetCookie(w, &http.Cookie{Name: stateCookie, Path: "/api/auth", MaxAge: -1, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode})

	var currentUser *int64
	if id, ok := s.currentUser(r); ok {
		currentUser = &id // живая сессия ⇒ добавление связки, не вход
	}
	token, expires, err := s.Auth.HandleCallback(r.Context(), provider, code, s.redirectURI(r, provider), currentUser)
	if err != nil {
		zap.S().Errorw("auth: oauth callback failed", "provider", provider, "err", err)
		return err
	}
	http.SetCookie(w, &http.Cookie{
		Name: sessionCookie, Value: token, Path: "/",
		Expires: expires, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode,
	})
	http.Redirect(w, r, s.FrontendURL, http.StatusFound)
	return nil
}

// POST /api/auth/logout.
func (s *Server) logout(w http.ResponseWriter, r *http.Request) error {
	if c, err := r.Cookie(sessionCookie); err == nil && c.Value != "" {
		if err := s.Auth.Logout(r.Context(), c.Value); err != nil {
			return err
		}
	}
	http.SetCookie(w, &http.Cookie{Name: sessionCookie, Path: "/", MaxAge: -1, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode})
	return noContent(w)
}

type meDTO struct {
	ID          int64         `json:"id"`
	DisplayName string        `json:"displayName"`
	Identities  []identityDTO `json:"identities"`
}

// GET /api/me.
func (s *Server) me(w http.ResponseWriter, r *http.Request) error {
	uid := userID(r)
	name, err := s.Store.UserDisplayName(r.Context(), uid)
	if err != nil {
		return err
	}
	idents, err := s.Store.Identities(r.Context(), uid)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, meDTO{ID: uid, DisplayName: name, Identities: mapSlice(idents, toIdentityDTO)})
}
