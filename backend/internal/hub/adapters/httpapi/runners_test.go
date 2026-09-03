package httpapi

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
)

func TestRunnerRoutes(t *testing.T) {
	db := testdb.Setup(t)
	h := &RunnersHandler{Store: &pgstore.Store{Pool: db}, Token: "runner-token"}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/runners", h.Auth(h.Register))
	mux.HandleFunc("POST /api/runners/{id}/heartbeat", h.Auth(h.Heartbeat))
	srv := httptest.NewServer(mux)
	defer srv.Close()

	post := func(path, token, body string) *http.Response {
		req, _ := http.NewRequest("POST", srv.URL+path, strings.NewReader(body))
		if token != "" {
			req.Header.Set("X-Runner-Token", token)
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		return resp
	}

	if resp := post("/api/runners", "wrong", `{"name":"r1","address":"http://r1","slots":2}`); resp.StatusCode != 401 {
		t.Fatalf("bad token: %d", resp.StatusCode)
	}
	if resp := post("/api/runners", "runner-token", `{"name":"r1","slots":2}`); resp.StatusCode != 400 {
		t.Fatalf("missing address: %d", resp.StatusCode)
	}
	if resp := post("/api/runners", "runner-token", `{"name":"r1","address":"http://r1","slots":2}`); resp.StatusCode != 200 {
		t.Fatalf("register: %d", resp.StatusCode)
	}
	// повторная регистрация того же имени — upsert, не конфликт
	if resp := post("/api/runners", "runner-token", `{"name":"r1","address":"http://r1b","slots":4}`); resp.StatusCode != 200 {
		t.Fatalf("re-register: %d", resp.StatusCode)
	}
	var n int
	var addr string
	if err := db.QueryRow(t.Context(),
		`SELECT count(*), max(address) FROM hub.runners`).Scan(&n, &addr); err != nil {
		t.Fatal(err)
	}
	if n != 1 || addr != "http://r1b" {
		t.Fatalf("runners: n=%d addr=%s", n, addr)
	}

	if resp := post("/api/runners/1/heartbeat", "runner-token", ""); resp.StatusCode != 204 {
		t.Fatalf("heartbeat: %d", resp.StatusCode)
	}
	if resp := post("/api/runners/999/heartbeat", "runner-token", ""); resp.StatusCode != 404 {
		t.Fatalf("heartbeat unknown: %d", resp.StatusCode)
	}
}
