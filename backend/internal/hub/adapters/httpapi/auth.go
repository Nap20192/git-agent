package httpapi

import (
	"context"
	"net/http"
)

type ctxKey int

const userIDKey ctxKey = 0

// Session — auth-middleware пользовательских роутов.
// TODO(auth, тикет 003): session cookie + OAuth-вход; пока пропускает всех
// под dev-пользователем (bootstrap в контейнере).
type Session struct {
	DevUserID int64
}

func (s *Session) Wrap(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		next(w, r.WithContext(context.WithValue(r.Context(), userIDKey, s.DevUserID)))
	}
}

func userID(r *http.Request) int64 {
	id, _ := r.Context().Value(userIDKey).(int64)
	return id
}
