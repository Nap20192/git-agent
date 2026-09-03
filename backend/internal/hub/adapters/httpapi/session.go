package httpapi

import (
	"context"
	"net/http"

	"go.uber.org/zap"
)

// Сессия (тикет 003).

const (
	sessionCookie = "hub_session"
	stateCookie   = "hub_oauth_state"
)

type ctxKey int

const userIDKey ctxKey = 0

func (s *Server) session(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		uid, ok := s.currentUser(r)
		if !ok && s.DevUserID != 0 {
			uid, ok = s.DevUserID, true
		}
		if !ok {
			unauthorized(w)
			return
		}
		next(w, r.WithContext(context.WithValue(r.Context(), userIDKey, uid)))
	}
}

func (s *Server) currentUser(r *http.Request) (int64, bool) {
	c, err := r.Cookie(sessionCookie)
	if err != nil || c.Value == "" {
		return 0, false
	}
	uid, ok, err := s.Store.SessionUser(r.Context(), c.Value)
	if err != nil {
		zap.S().Errorw("auth: session lookup failed", "err", err)
		return 0, false
	}
	return uid, ok
}

func userID(r *http.Request) int64 {
	id, _ := r.Context().Value(userIDKey).(int64)
	return id
}
