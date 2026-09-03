package app

import (
	"bytes"
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/oauth"
	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// Refresh-флоу по 401 (GitLab): fn падает с ErrUnauthorized → refresh у
// провайдера → новые токены в БД → повтор fn свежим токеном.
func TestCallWithTokenRefresh(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	box, _ := secrets.New(bytes.Repeat([]byte{5}, 32))
	store := &pgstore.Store{Pool: db}

	var refreshCalls atomic.Int64
	fakeGitLab := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/oauth/token" || r.FormValue("grant_type") != "refresh_token" {
			t.Errorf("unexpected call: %s %v", r.URL.Path, r.Form)
			w.WriteHeader(http.StatusNotFound)
			return
		}
		if r.FormValue("refresh_token") != "old-refresh" {
			t.Errorf("refresh token: %s", r.FormValue("refresh_token"))
		}
		refreshCalls.Add(1)
		fmt.Fprint(w, `{"access_token":"fresh-access","refresh_token":"fresh-refresh","expires_in":7200}`)
	}))
	defer fakeGitLab.Close()

	accessEnc, _ := box.Encrypt([]byte("stale-access"))
	refreshEnc, _ := box.Encrypt([]byte("old-refresh"))
	var identID int64
	if err := db.QueryRow(ctx, `
		WITH u AS (INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id)
		INSERT INTO hub.identities (user_id, provider, provider_user_id, username, access_token_enc, refresh_token_enc)
		SELECT id, 'gitlab', 'gl-1', 't', $1, $2 FROM u RETURNING id`,
		accessEnc, refreshEnc).Scan(&identID); err != nil {
		t.Fatal(err)
	}

	svc := &AuthService{
		Store: store, Secrets: box,
		OAuth: &oauth.Client{
			GitLab:    oauth.App{ClientID: "cid", ClientSecret: "csec"},
			GitLabURL: fakeGitLab.URL,
		},
	}
	ident, err := store.FindIdentityByProviderUser(ctx, "gitlab", "gl-1")
	if err != nil || ident == nil {
		t.Fatal(err)
	}

	var seen []string
	err = svc.CallWithToken(ctx, ident, func(token string) error {
		seen = append(seen, token)
		if token == "stale-access" {
			return fmt.Errorf("provider says no: %w", domain.ErrUnauthorized)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(seen) != 2 || seen[0] != "stale-access" || seen[1] != "fresh-access" {
		t.Fatalf("tokens seen: %v", seen)
	}
	if refreshCalls.Load() != 1 {
		t.Fatalf("refresh calls: %d", refreshCalls.Load())
	}

	// новые токены персистнуты шифром
	fresh, err := store.FindIdentityByProviderUser(ctx, "gitlab", "gl-1")
	if err != nil || fresh == nil {
		t.Fatal(err)
	}
	access, _ := box.Decrypt(fresh.AccessTokenEnc)
	refresh, _ := box.Decrypt(fresh.RefreshTokenEnc)
	if string(access) != "fresh-access" || string(refresh) != "fresh-refresh" {
		t.Fatalf("persisted tokens: %q / %q", access, refresh)
	}
	if fresh.TokenExpiresAt == nil {
		t.Error("token_expires_at not persisted")
	}
}

// Без refresh-токена (GitHub) 401 отдаётся как есть, refresh не пытается.
func TestCallWithTokenNoRefreshToken(t *testing.T) {
	box, _ := secrets.New(bytes.Repeat([]byte{5}, 32))
	accessEnc, _ := box.Encrypt([]byte("gh-token"))
	svc := &AuthService{Secrets: box}
	calls := 0
	err := svc.CallWithToken(context.Background(),
		&domain.Identity{Provider: "github", AccessTokenEnc: accessEnc},
		func(token string) error {
			calls++
			return fmt.Errorf("nope: %w", domain.ErrUnauthorized)
		})
	if err == nil || calls != 1 {
		t.Fatalf("err=%v calls=%d", err, calls)
	}
}
