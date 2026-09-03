package opensandbox

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestCreateSandboxNoTTL(t *testing.T) {
	var got struct {
		method, path, key string
		body              map[string]json.RawMessage
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got.method, got.path, got.key = r.Method, r.URL.Path, r.Header.Get(headerAPIKey)
		b, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(b, &got.body)
		w.WriteHeader(http.StatusAccepted)
		_, _ = w.Write([]byte(`{"id":"sbx-1","status":"running"}`))
	}))
	defer srv.Close()

	c := &Client{}
	id, err := c.CreateSandbox(context.Background(), srv.URL, "dev-key", "alpine/git:latest")
	if err != nil {
		t.Fatal(err)
	}
	if id != "sbx-1" {
		t.Fatalf("id = %q", id)
	}
	if got.method != "POST" || got.path != "/v1/sandboxes" || got.key != "dev-key" {
		t.Fatalf("request = %+v", got)
	}
	// no-TTL: timeout обязан присутствовать и быть явным null
	timeout, ok := got.body["timeout"]
	if !ok || string(timeout) != "null" {
		t.Fatalf("timeout = %q (present=%v), want explicit null", timeout, ok)
	}
	if string(got.body["image"]) != `{"uri":"alpine/git:latest"}` {
		t.Fatalf("image = %s", got.body["image"])
	}
	if !strings.Contains(string(got.body["env"]), "EXECD_API_GRACE_SHUTDOWN") {
		t.Fatalf("env = %s, want EXECD_API_GRACE_SHUTDOWN", got.body["env"])
	}
}

func TestDeleteSandboxTolerates404(t *testing.T) {
	status := http.StatusOK
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "DELETE" || r.URL.Path != "/v1/sandboxes/sbx-1" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		w.WriteHeader(status)
	}))
	defer srv.Close()

	c := &Client{}
	if err := c.DeleteSandbox(context.Background(), srv.URL, "", "sbx-1"); err != nil {
		t.Fatal(err)
	}
	status = http.StatusNotFound // уже убит — идемпотентно ок
	if err := c.DeleteSandbox(context.Background(), srv.URL, "", "sbx-1"); err != nil {
		t.Fatal(err)
	}
	status = http.StatusInternalServerError
	if err := c.DeleteSandbox(context.Background(), srv.URL, "", "sbx-1"); err == nil {
		t.Fatal("want error on 500")
	}
}

func TestBaseURLSchemeDefault(t *testing.T) {
	if got := baseURL("sb.local:8090"); got != "http://sb.local:8090/v1" {
		t.Fatal(got)
	}
	if got := baseURL("https://sb.example"); got != "https://sb.example/v1" {
		t.Fatal(got)
	}
}
