package app

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/provider"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// Connect: репозиторий провайдера → строка hub.repositories с шифрованным
// per-repo секретом + hook у провайдера с URL из WEBHOOK_BASE_URL и id репо.
func TestRepositoryConnect(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	box, _ := secrets.New(bytes.Repeat([]byte{3}, 32))
	store := &pgstore.Store{Pool: db}

	tokenEnc, _ := box.Encrypt([]byte("gh-token"))
	var userID, identityID int64
	if err := db.QueryRow(ctx, `
		WITH u AS (INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id)
		INSERT INTO hub.identities (user_id, provider, provider_user_id, username, access_token_enc)
		SELECT id, 'github', 'gh-1', 't', $1 FROM u RETURNING user_id, id`, tokenEnc,
	).Scan(&userID, &identityID); err != nil {
		t.Fatal(err)
	}

	var hookBody map[string]any
	fakeGitHub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer gh-token" {
			t.Errorf("bad auth header: %s", r.Header.Get("Authorization"))
		}
		switch {
		case r.Method == "GET" && r.URL.Path == "/repositories/100":
			fmt.Fprint(w, `{"id":100,"name":"repo","owner":{"login":"acme"},"default_branch":"main","private":true}`)
		case r.Method == "POST" && r.URL.Path == "/repos/acme/repo/hooks":
			if err := json.NewDecoder(r.Body).Decode(&hookBody); err != nil {
				t.Error(err)
			}
			w.WriteHeader(http.StatusCreated)
			fmt.Fprint(w, `{"id":777}`)
		default:
			t.Errorf("unexpected provider call: %s %s", r.Method, r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer fakeGitHub.Close()

	svc := &RepositoryService{
		Repos: store, Identities: store,
		Provider:       &provider.Client{GitHubBase: fakeGitHub.URL},
		Auth:           &AuthService{Secrets: box},
		Secrets:        box,
		WebhookBaseURL: "https://hub.example",
	}
	repo, err := svc.Connect(ctx, userID, identityID, "100", nil)
	if err != nil {
		t.Fatal(err)
	}
	if repo.Owner != "acme" || repo.Name != "repo" || *repo.WebhookProviderID != "777" {
		t.Errorf("repo: %+v", repo)
	}

	// URL хука содержит id свежесозданного репозитория
	cfg := hookBody["config"].(map[string]any)
	wantURL := fmt.Sprintf("https://hub.example/hooks/github/%d", repo.ID)
	if cfg["url"] != wantURL {
		t.Errorf("hook url: %v, want %s", cfg["url"], wantURL)
	}

	// per-repo секрет в БД шифром и расшифровывается в тот же, что уехал провайдеру
	stored, err := store.Repository(ctx, repo.ID, userID)
	if err != nil || stored == nil {
		t.Fatal(err)
	}
	secret, err := box.Decrypt(stored.WebhookSecretEnc)
	if err != nil {
		t.Fatal(err)
	}
	if string(secret) != cfg["secret"] {
		t.Error("stored secret differs from provider hook secret")
	}
}

// Провайдер отказал в создании хука — строка репозитория откатывается.
func TestRepositoryConnectHookFailureRollsBack(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	box, _ := secrets.New(bytes.Repeat([]byte{3}, 32))
	store := &pgstore.Store{Pool: db}

	tokenEnc, _ := box.Encrypt([]byte("gh-token"))
	var userID, identityID int64
	if err := db.QueryRow(ctx, `
		WITH u AS (INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id)
		INSERT INTO hub.identities (user_id, provider, provider_user_id, username, access_token_enc)
		SELECT id, 'github', 'gh-1', 't', $1 FROM u RETURNING user_id, id`, tokenEnc,
	).Scan(&userID, &identityID); err != nil {
		t.Fatal(err)
	}

	fakeGitHub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "GET" {
			fmt.Fprint(w, `{"id":100,"name":"repo","owner":{"login":"acme"}}`)
			return
		}
		w.WriteHeader(http.StatusForbidden) // hook creation denied
	}))
	defer fakeGitHub.Close()

	svc := &RepositoryService{
		Repos: store, Identities: store,
		Provider:       &provider.Client{GitHubBase: fakeGitHub.URL},
		Auth:           &AuthService{Secrets: box},
		Secrets:        box,
		WebhookBaseURL: "https://hub.example",
	}
	if _, err := svc.Connect(ctx, userID, identityID, "100", nil); err == nil {
		t.Fatal("expected error")
	}
	var n int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM hub.repositories`).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 0 {
		t.Fatalf("repositories after rollback: %d", n)
	}
}

// ── watch-режим (тикет 015): чужой публичный репо по URL, без хука ──────────

func seedUser(t *testing.T, ctx context.Context, db *pgxpool.Pool) int64 {
	t.Helper()
	var userID int64
	if err := db.QueryRow(ctx, `INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id`).Scan(&userID); err != nil {
		t.Fatal(err)
	}
	return userID
}

func TestParseRepoURL(t *testing.T) {
	ok := map[string][3]string{
		"https://github.com/acme/repo":        {"github", "acme", "repo"},
		"https://github.com/acme/repo.git/":   {"github", "acme", "repo"},
		"https://gitlab.com/grp/sub/repo":     {"gitlab", "grp/sub", "repo"},
		" https://www.github.com/acme/repo\n": {"github", "acme", "repo"},
	}
	for raw, want := range ok {
		p, o, n, err := ParseRepoURL(raw)
		if err != nil || [3]string{p, o, n} != want {
			t.Errorf("%q → %v %v %v %v, want %v", raw, p, o, n, err, want)
		}
	}
	for _, raw := range []string{"", "acme/repo", "http://github.com/acme/repo", "https://bitbucket.org/a/b",
		"https://github.com/acme", "https://github.com/acme/repo/pulls", "https://gitlab.com/repo"} {
		if _, _, _, err := ParseRepoURL(raw); !errors.Is(err, domain.ErrInvalid) {
			t.Errorf("%q: want ErrInvalid, got %v", raw, err)
		}
	}
}

// ConnectPublic: публичный репо → строка mode=watch без связки/хука/секрета,
// провайдер спрошен без Authorization; приватный/несуществующий → 422.
func TestRepositoryConnectPublic(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	store := &pgstore.Store{Pool: db}
	userID := seedUser(t, ctx, db)

	fakeGitHub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "" {
			t.Errorf("public API must be called without a token, got %q", r.Header.Get("Authorization"))
		}
		switch r.URL.Path {
		case "/repos/acme/pub":
			fmt.Fprint(w, `{"id":500,"name":"pub","owner":{"login":"acme"},"default_branch":"trunk","private":false}`)
		case "/repos/acme/priv":
			fmt.Fprint(w, `{"id":501,"name":"priv","owner":{"login":"acme"},"private":true}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer fakeGitHub.Close()

	svc := &RepositoryService{Repos: store, Identities: store, Subs: store, Provider: &provider.Client{GitHubBase: fakeGitHub.URL}}

	repo, err := svc.ConnectPublic(ctx, userID, "https://github.com/acme/pub", nil)
	if err != nil {
		t.Fatal(err)
	}
	stored, err := store.Repository(ctx, repo.ID, userID)
	if err != nil || stored == nil {
		t.Fatal(err)
	}
	if stored.Mode != "watch" || stored.IdentityID != nil || stored.WebhookProviderID != nil || stored.WebhookSecretEnc != nil ||
		stored.ExternalID != "500" || stored.Owner != "acme" || stored.Name != "pub" || *stored.DefaultBranch != "trunk" {
		t.Errorf("stored: %+v", stored)
	}

	for _, u := range []string{"https://github.com/acme/priv", "https://github.com/acme/missing"} {
		if _, err := svc.ConnectPublic(ctx, userID, u, nil); !errors.Is(err, domain.ErrUnprocessable) {
			t.Errorf("%s: want ErrUnprocessable, got %v", u, err)
		}
	}
	if _, err := svc.ConnectPublic(ctx, userID, "https://bitbucket.org/a/b", nil); !errors.Is(err, domain.ErrInvalid) {
		t.Errorf("bad url: want ErrInvalid, got %v", err)
	}
	var n int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM hub.repositories`).Scan(&n); err != nil || n != 1 {
		t.Errorf("repositories: %d (%v), want 1", n, err)
	}

	// Disconnect watch-репо не ходит к провайдеру
	fakeGitHub.Close()
	if err := svc.Disconnect(ctx, repo.ID, userID); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRow(ctx, `SELECT count(*) FROM hub.repositories`).Scan(&n); err != nil || n != 0 {
		t.Errorf("repositories after disconnect: %d (%v)", n, err)
	}
}

// Trigger watch-репо без связки: HEAD резолвится публичным API без токена.
func TestRepositoryTriggerWatchWithoutIdentity(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	box, _ := secrets.New(bytes.Repeat([]byte{3}, 32))
	store := &pgstore.Store{Pool: db}
	userID := seedUser(t, ctx, db)

	var repoID int64
	if err := db.QueryRow(ctx, `INSERT INTO hub.repositories (user_id, mode, provider, external_id, owner, name, default_branch)
		VALUES ($1, 'watch', 'github', '500', 'acme', 'pub', 'main') RETURNING id`, userID).Scan(&repoID); err != nil {
		t.Fatal(err)
	}
	fakeGitHub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "" {
			t.Errorf("public API must be called without a token, got %q", r.Header.Get("Authorization"))
		}
		if r.URL.Path != "/repos/acme/pub/commits/main" {
			http.NotFound(w, r)
			return
		}
		fmt.Fprint(w, `{"sha":"headsha"}`)
	}))
	defer fakeGitHub.Close()

	svc := &RepositoryService{
		Repos: store, Identities: store, Subs: store,
		Provider: &provider.Client{GitHubBase: fakeGitHub.URL},
		Auth:     &AuthService{Store: store, Secrets: box},
		Webhook:  &WebhookService{Repos: store, Subs: store, Ingestor: store, Secrets: box},
	}
	res, err := svc.Trigger(ctx, userID, repoID, "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if res.CommitSHA != "headsha" || res.Duplicate {
		t.Errorf("trigger: %+v", res)
	}
}
