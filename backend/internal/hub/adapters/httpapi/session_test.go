package httpapi

import (
	"context"
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// seedSession — живая сессия пользователя; возвращает cookie для запросов.
func seedSession(t *testing.T, db *pgxpool.Pool, userID int64) *http.Cookie {
	t.Helper()
	token := fmt.Sprintf("test-session-%d-%d", userID, time.Now().UnixNano())
	if _, err := db.Exec(context.Background(),
		`INSERT INTO hub.sessions (token, user_id, expires_at) VALUES ($1, $2, now() + interval '1 hour')`,
		token, userID); err != nil {
		t.Fatal(err)
	}
	return &http.Cookie{Name: sessionCookie, Value: token}
}
