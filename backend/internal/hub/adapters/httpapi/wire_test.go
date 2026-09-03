package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/vnkjd/git-agent/backend/pkg/trace"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

type apiErr struct {
	Error struct{ Code, Message string } `json:"error"`
}

func decodeErr(t *testing.T, rec *httptest.ResponseRecorder) apiErr {
	t.Helper()
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Fatalf("content-type %q", ct)
	}
	var e apiErr
	if err := json.Unmarshal(rec.Body.Bytes(), &e); err != nil {
		t.Fatalf("body %q: %v", rec.Body.String(), err)
	}
	return e
}

func TestWriteError_WireFormat(t *testing.T) {
	cases := []struct {
		err    error
		status int
		code   string
		msg    string
	}{
		{domain.ErrNotFound, 404, "not_found", "not found"},
		{fmt.Errorf("instance is down — raise the agent first: %w", domain.ErrConflict), 409, "conflict", "instance is down — raise the agent first"},
		{fmt.Errorf("identity 7 is not connected: %w", domain.ErrNotFound), 404, "not_found", "identity 7 is not connected"},
		{fmt.Errorf("opensandbox POST /sandboxes: status 401: bad key: %w", domain.ErrUpstream), 502, "upstream", "opensandbox POST /sandboxes: status 401: bad key"},
		{fmt.Errorf("mode must be manual: %w", domain.ErrInvalid), 400, "bad_request", "mode must be manual"},
		{domain.ErrUnavailable, 503, "unavailable", "provider is not configured (set *_OAUTH_CLIENT_ID/SECRET in .env)"},
		{errors.New("pq: connection refused"), 500, "internal", "internal error: pq: connection refused"},
	}
	for _, c := range cases {
		rec := httptest.NewRecorder()
		writeError(context.Background(), rec, c.err)
		e := decodeErr(t, rec)
		if rec.Code != c.status || e.Error.Code != c.code || e.Error.Message != c.msg {
			t.Errorf("%v → %d %q %q; want %d %q %q", c.err, rec.Code, e.Error.Code, e.Error.Message, c.status, c.code, c.msg)
		}
	}
}

func TestDecodeBody_ReadableErrors(t *testing.T) {
	for body, want := range map[string]string{"": "request body is required", "{oops": "invalid JSON body: "} {
		rec := httptest.NewRecorder()
		var v map[string]any
		err := decode(httptest.NewRequest("POST", "/", strings.NewReader(body)), &v)
		if err == nil {
			t.Fatalf("%q decoded", body)
		}
		writeError(context.Background(), rec, err)
		if e := decodeErr(t, rec); rec.Code != 400 || !strings.HasPrefix(e.Error.Message, want) {
			t.Errorf("%q → %d %q", body, rec.Code, e.Error.Message)
		}
	}
}

func TestRecover_PanicTo500(t *testing.T) {
	h := Recover(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { panic("boom") }))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", "/", nil))
	if e := decodeErr(t, rec); rec.Code != 500 || e.Error.Message != "internal error: panic: boom" {
		t.Errorf("%d %q", rec.Code, e.Error.Message)
	}
}

// Logging: X-Trace-Id принимается (в нижнем регистре), иначе генерируется;
// в ответе тот же заголовок; в ctx хендлера — тот же id.
func TestLogging_TraceID(t *testing.T) {
	var seen string
	h := Logging(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = trace.FromContext(r.Context())
	}))
	given := "ABCDEF0123456789abcdef0123456789"
	req := httptest.NewRequest("GET", "/api/me", nil)
	req.Header.Set(trace.Header, given)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if want := strings.ToLower(given); seen != want || rec.Header().Get(trace.Header) != want {
		t.Fatalf("accept: ctx=%q header=%q", seen, rec.Header().Get(trace.Header))
	}

	for _, bad := range []string{"", "not-a-trace"} {
		req := httptest.NewRequest("GET", "/api/me", nil)
		req.Header.Set(trace.Header, bad)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		got := rec.Header().Get(trace.Header)
		if !trace.Valid(got) || got != seen {
			t.Fatalf("generate for %q: header=%q ctx=%q", bad, got, seen)
		}
	}
}
