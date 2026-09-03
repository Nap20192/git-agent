package httpapi

import (
	"crypto/rand"
	"errors"
	"log/slog"
	"net/http"
	"runtime/debug"
	"time"

	"github.com/vnkjd/git-agent/backend/pkg/logger"
)

// Wrap — внешний слой HTTP-поверхности: request id (X-Request-ID сквозной либо
// свой), recover паники в 500 JSON, access-log одной строкой на запрос.
func Wrap(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reqID := r.Header.Get("X-Request-ID")
		if !validRequestID(reqID) {
			reqID = rand.Text()
		}
		w.Header().Set("X-Request-ID", reqID)
		w.Header().Set("X-Content-Type-Options", "nosniff")
		r = r.WithContext(logger.WithRequestID(r.Context(), reqID))
		sw := &statusWriter{ResponseWriter: w}
		start := time.Now()

		defer func() {
			if p := recover(); p != nil {
				if err, ok := p.(error); ok && errors.Is(err, http.ErrAbortHandler) {
					panic(p) // штатный сигнал net/http, не наша паника
				}
				slog.ErrorContext(r.Context(), "httpapi: panic", "panic", p, "stack", string(debug.Stack()))
				if !sw.wrote {
					errorJSON(w, http.StatusInternalServerError, "internal")
				}
			}
			if r.URL.Path == "/healthz" {
				return
			}
			lvl := slog.LevelInfo
			if sw.status >= 500 {
				lvl = slog.LevelError
			}
			slog.Log(r.Context(), lvl, "http",
				"method", r.Method, "path", r.URL.Path, "route", r.Pattern, "status", sw.status, "remote", r.RemoteAddr,
				"bytes", sw.bytes, "durationMs", time.Since(start).Milliseconds())
		}()
		next.ServeHTTP(sw, r)
	})
}

// validRequestID — чужой X-Request-ID берём только короткий и печатный:
// заголовок недоверенный, в лог и в ответ попадёт как есть.
func validRequestID(id string) bool {
	if id == "" || len(id) > 64 {
		return false
	}
	for _, c := range id {
		if c <= ' ' || c > '~' {
			return false
		}
	}
	return true
}

// statusWriter — запоминает статус/байты; Flush и Unwrap сохраняют SSE.
type statusWriter struct {
	http.ResponseWriter
	status int
	bytes  int
	wrote  bool
}

func (w *statusWriter) WriteHeader(code int) {
	if !w.wrote {
		w.status, w.wrote = code, true
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *statusWriter) Write(b []byte) (int, error) {
	if !w.wrote {
		w.status, w.wrote = http.StatusOK, true
	}
	n, err := w.ResponseWriter.Write(b)
	w.bytes += n
	return n, err
}

func (w *statusWriter) Flush() {
	if f, ok := w.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func (w *statusWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }
