package httpapi

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
	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
)

// POST /api/repositories {url} — watch-режим (тикет 015): 201 с mode=watch и
// identityId=null; приватный/несуществующий — 422; кривой URL — 400.
func TestConnectRepositoryByURL(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	var userID int64
	if err := db.QueryRow(ctx, `INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id`).Scan(&userID); err != nil {
		t.Fatal(err)
	}
	gh := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/repos/acme/pub":
			fmt.Fprint(w, `{"id":500,"name":"pub","owner":{"login":"acme"},"default_branch":"main","private":false}`)
		case "/repos/acme/priv":
			fmt.Fprint(w, `{"id":501,"name":"priv","owner":{"login":"acme"},"private":true}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer gh.Close()

	store := &pgstore.Store{Pool: db}
	svc := &app.RepositoryService{Repos: store, Identities: store, Subs: store, Provider: &provider.Client{GitHubBase: gh.URL}}
	srv := httptest.NewServer(Logging(NewMux(&Server{Store: store, Repositories: svc, DevUserID: userID})))
	defer srv.Close()

	post := func(body string) (int, map[string]any) {
		t.Helper()
		resp, err := http.Post(srv.URL+"/api/repositories", "application/json", bytes.NewBufferString(body))
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		var out map[string]any
		_ = json.NewDecoder(resp.Body).Decode(&out)
		return resp.StatusCode, out
	}

	code, out := post(`{"url":"https://github.com/acme/pub"}`)
	if code != http.StatusCreated || out["mode"] != "watch" || out["identityId"] != nil || out["externalId"] != "500" {
		t.Errorf("public: %d %v", code, out)
	}
	for _, url := range []string{"https://github.com/acme/priv", "https://github.com/acme/missing"} {
		if code, out := post(fmt.Sprintf(`{"url":%q}`, url)); code != http.StatusUnprocessableEntity {
			t.Errorf("%s: %d %v", url, code, out)
		}
	}
	if code, out := post(`{"url":"https://bitbucket.org/a/b"}`); code != http.StatusBadRequest {
		t.Errorf("bad host: %d %v", code, out)
	}
	if code, out := post(`{}`); code != http.StatusBadRequest {
		t.Errorf("empty body: %d %v", code, out)
	}
}
