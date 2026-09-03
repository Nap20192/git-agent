package app

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/provider"
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
