package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestReplayPreservesPathHeadersBody(t *testing.T) {
	var got *http.Request
	var gotBody []byte
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Clone(r.Context())
		gotBody, _ = io.ReadAll(r.Body)
	}))
	defer hub.Close()

	rec := record{
		Path: "/hooks/github/42",
		Headers: http.Header{
			"Content-Type":        {"application/json"},
			"X-Github-Event":      {"push"},
			"X-Github-Delivery":   {"d-1"},
			"X-Hub-Signature-256": {"sha256=abc"},
			"Host":                {"relay.example.com"},
		},
		Body: []byte(`{"x":1}`),
	}
	if err := replay(hub.Client(), hub.URL, rec); err != nil {
		t.Fatalf("replay: %v", err)
	}
	if got.URL.Path != "/hooks/github/42" || got.Method != "POST" {
		t.Fatalf("path/method: %s %s", got.Method, got.URL.Path)
	}
	for k, want := range map[string]string{
		"Content-Type":        "application/json",
		"X-Github-Event":      "push",
		"X-Github-Delivery":   "d-1",
		"X-Hub-Signature-256": "sha256=abc",
	} {
		if got.Header.Get(k) != want {
			t.Fatalf("header %s: %q", k, got.Header.Get(k))
		}
	}
	if got.Host == "relay.example.com" {
		t.Fatal("Host header replayed")
	}
	if string(gotBody) != `{"x":1}` {
		t.Fatalf("body: %s", gotBody)
	}
}

func TestReplayHubError(t *testing.T) {
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(500)
	}))
	defer hub.Close()
	if err := replay(hub.Client(), hub.URL, record{Path: "/hooks/github/1"}); err == nil {
		t.Fatal("want error on hub 500")
	}
}

func TestPull(t *testing.T) {
	relay := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Relay-Token") != "tok" {
			w.WriteHeader(401)
			return
		}
		_ = json.NewEncoder(w).Encode([]record{{Path: "/hooks/gitlab/7", Body: []byte("b")}})
	}))
	defer relay.Close()

	recs, err := pull(relay.Client(), relay.URL, "tok")
	if err != nil || len(recs) != 1 || recs[0].Path != "/hooks/gitlab/7" || string(recs[0].Body) != "b" {
		t.Fatalf("pull: %v %+v", err, recs)
	}
	if _, err := pull(relay.Client(), relay.URL, "bad"); err == nil {
		t.Fatal("want error on 401")
	}
}
