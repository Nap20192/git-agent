package main

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func doPull(t *testing.T, q *queue, token, query string) (int, []record) {
	t.Helper()
	h := newHandler(q, "tok")
	req := httptest.NewRequest("GET", "/pull"+query, nil)
	req.Header.Set("X-Relay-Token", token)
	rw := httptest.NewRecorder()
	h.ServeHTTP(rw, req)
	var recs []record
	if rw.Code == 200 {
		if err := json.Unmarshal(rw.Body.Bytes(), &recs); err != nil {
			t.Fatalf("decode pull: %v", err)
		}
	}
	return rw.Code, recs
}

func TestPushPull(t *testing.T) {
	q := newQueue()
	h := newHandler(q, "tok")

	req := httptest.NewRequest("POST", "/hooks/github/42", strings.NewReader(`{"x":1}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-GitHub-Event", "push")
	req.Header.Set("X-Hub-Signature-256", "sha256=abc")
	rw := httptest.NewRecorder()
	h.ServeHTTP(rw, req)
	if rw.Code != 200 {
		t.Fatalf("push: code %d", rw.Code)
	}

	code, recs := doPull(t, q, "tok", "")
	if code != 200 || len(recs) != 1 {
		t.Fatalf("pull: code %d, recs %d", code, len(recs))
	}
	r := recs[0]
	if r.Path != "/hooks/github/42" || string(r.Body) != `{"x":1}` ||
		r.Headers.Get("X-Hub-Signature-256") != "sha256=abc" || r.Headers.Get("X-GitHub-Event") != "push" {
		t.Fatalf("record mismatch: %+v", r)
	}

	if _, recs := doPull(t, q, "tok", ""); len(recs) != 0 {
		t.Fatalf("second pull not empty: %d", len(recs))
	}
}

func TestPullBadToken(t *testing.T) {
	if code, _ := doPull(t, newQueue(), "wrong", ""); code != 401 {
		t.Fatalf("want 401, got %d", code)
	}
}

func TestOverflow(t *testing.T) {
	q := newQueue()
	for i := 0; i < maxQueue+5; i++ {
		q.push(record{Path: fmt.Sprintf("/hooks/github/%d", i)})
	}
	_, recs := doPull(t, q, "tok", "")
	if len(recs) != maxQueue {
		t.Fatalf("want %d records, got %d", maxQueue, len(recs))
	}
	if recs[0].Path != "/hooks/github/5" {
		t.Fatalf("oldest not evicted, first: %s", recs[0].Path)
	}
}

func TestLongPollWakesOnPush(t *testing.T) {
	q := newQueue()
	go func() {
		time.Sleep(50 * time.Millisecond)
		q.push(record{Path: "/hooks/github/1"})
	}()
	start := time.Now()
	code, recs := doPull(t, q, "tok", "?wait=2s")
	if code != 200 || len(recs) != 1 {
		t.Fatalf("code %d, recs %d", code, len(recs))
	}
	if time.Since(start) > time.Second {
		t.Fatalf("long poll did not wake on push, took %v", time.Since(start))
	}
}
