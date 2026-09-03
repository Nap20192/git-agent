package httpapi

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// Инвариант redaction: сырой ключ не покидает hub ни в create-ответе, ни в листинге.
func TestLlmConnectionRedaction(t *testing.T) {
	db := testdb.Setup(t)
	box, _ := secrets.New(bytes.Repeat([]byte{2}, 32))
	store := &pgstore.Store{Pool: db}

	var userID int64
	if err := db.QueryRow(t.Context(),
		`INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id`).Scan(&userID); err != nil {
		t.Fatal(err)
	}

	cookie := seedSession(t, db, userID)
	srv := httptest.NewServer(NewMux(&Server{Store: store, Connections: &app.ConnectionService{Store: store, Secrets: box}}))
	defer srv.Close()

	const rawKey = "sk-super-secret-key-9876"
	req, _ := http.NewRequest("POST", srv.URL+"/api/connections/llm",
		strings.NewReader(`{"name":"main","apiBase":"https://llm.example","apiKey":"`+rawKey+`","model":"m1"}`))
	req.AddCookie(cookie)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	var created map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&created); err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 201 {
		t.Fatalf("create: %d", resp.StatusCode)
	}
	if created["apiKeyMasked"] != "…9876" {
		t.Errorf("masked: %v", created["apiKeyMasked"])
	}

	req, _ = http.NewRequest("GET", srv.URL+"/api/connections/llm", nil)
	req.AddCookie(cookie)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	if _, err := buf.ReadFrom(resp.Body); err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if bytes.Contains(buf.Bytes(), []byte(rawKey)) {
		t.Fatal("raw api key leaked in list response")
	}
	var list []map[string]any
	if err := json.Unmarshal(buf.Bytes(), &list); err != nil {
		t.Fatal(err)
	}
	if len(list) != 1 || list[0]["apiKeyMasked"] != "…9876" {
		t.Fatalf("list: %+v", list)
	}
}
