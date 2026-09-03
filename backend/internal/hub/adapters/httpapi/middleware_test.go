package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/logger"
)

func TestWrapRequestIDAndRecover(t *testing.T) {
	h := Wrap(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/boom" {
			panic("boom")
		}
		w.Write([]byte(logger.RequestID(r.Context())))
	}))

	// сквозной X-Request-ID попадает в ctx и в ответ
	w := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/ok", nil)
	req.Header.Set("X-Request-ID", "abc")
	h.ServeHTTP(w, req)
	if w.Body.String() != "abc" || w.Header().Get("X-Request-ID") != "abc" {
		t.Fatalf("request id not threaded: body=%q hdr=%q", w.Body.String(), w.Header().Get("X-Request-ID"))
	}

	// без заголовка — генерируем
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/ok", nil))
	if w.Body.String() == "" || w.Body.String() != w.Header().Get("X-Request-ID") {
		t.Fatalf("generated id mismatch: body=%q hdr=%q", w.Body.String(), w.Header().Get("X-Request-ID"))
	}

	// паника — 500 JSON, не обрыв соединения
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/boom", nil))
	if w.Code != 500 || !strings.Contains(w.Body.String(), `"internal"`) {
		t.Fatalf("panic: status=%d body=%s", w.Code, w.Body.String())
	}
}

func TestWriteErrorMapping(t *testing.T) {
	cases := []struct {
		err    error
		status int
	}{
		{domain.ErrNotFound, 404}, {domain.ErrConflict, 409}, {domain.ErrUnavailable, 503},
		{domain.ErrUnauthorized, 502}, {domain.ErrTimeout, 504}, {errors.New("db down"), 500},
	}
	for _, tc := range cases {
		w := httptest.NewRecorder()
		r := httptest.NewRequest("GET", "/", nil)
		r = r.WithContext(logger.WithRequestID(r.Context(), "rid"))
		writeError(w, r, tc.err)
		if w.Code != tc.status || w.Header().Get("Content-Type") != "application/json" {
			t.Fatalf("%v: status=%d ct=%q", tc.err, w.Code, w.Header().Get("Content-Type"))
		}
		var body map[string]string
		if json.Unmarshal(w.Body.Bytes(), &body) != nil || body["error"] == "" {
			t.Fatalf("%v: bad body %s", tc.err, w.Body.String())
		}
		if tc.status == 500 && body["requestId"] != "rid" {
			t.Fatalf("500 without requestId: %s", w.Body.String())
		}
	}
	// обрыв клиента — 499, тела нет, не ошибка сервера
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	w := httptest.NewRecorder()
	writeError(w, httptest.NewRequest("GET", "/", nil).WithContext(ctx), errors.New("pgx: canceled"))
	if w.Code != 499 || w.Body.Len() != 0 {
		t.Fatalf("canceled: status=%d body=%s", w.Code, w.Body.String())
	}

	// тело больше лимита — 413
	w = httptest.NewRecorder()
	big := httptest.NewRequest("POST", "/", strings.NewReader(`{"x":"`+strings.Repeat("a", maxJSONBody+1)+`"}`))
	var v map[string]any
	if decodeBody(w, big, &v) || w.Code != 413 {
		t.Fatalf("oversized body: status=%d", w.Code)
	}
}
