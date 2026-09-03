// Package httpapi — inbound-адаптер HTTP (wire-формат backend/docs/openapi.yaml).
package httpapi

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"runtime/debug"
	"strconv"
	"strings"
	"time"

	"go.uber.org/zap"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

type handler func(w http.ResponseWriter, r *http.Request) error

func handle(fn handler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if err := fn(w, r); err != nil {
			writeError(w, err)
		}
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		zap.S().Errorw("httpapi: encode response", "err", err)
	}
}

func respond(w http.ResponseWriter, status int, v any) error {
	writeJSON(w, status, v)
	return nil
}

func noContent(w http.ResponseWriter) error {
	w.WriteHeader(http.StatusNoContent)
	return nil
}

var errStatus = []struct {
	sentinel       error
	status         int
	code, fallback string
}{
	{domain.ErrInvalid, http.StatusBadRequest, "bad_request", "invalid request"},
	{domain.ErrUnauthorized, http.StatusUnauthorized, "unauthorized", "unauthorized"},
	{domain.ErrNotFound, http.StatusNotFound, "not_found", "not found"},
	{domain.ErrConflict, http.StatusConflict, "conflict", "conflict"},
	{domain.ErrUpstream, http.StatusBadGateway, "upstream", "upstream service failed"},
	{domain.ErrUnavailable, http.StatusServiceUnavailable, "unavailable", "provider is not configured (set *_OAUTH_CLIENT_ID/SECRET in .env)"},
	{domain.ErrTimeout, http.StatusGatewayTimeout, "timeout", "runner did not start streaming in time (queued too long)"},
}

// writeError — {"error":{"code","message"}} (зеркало frontend ApiError).
func writeError(w http.ResponseWriter, err error) {
	for _, m := range errStatus {
		if errors.Is(err, m.sentinel) {
			writeAPIError(w, m.status, m.code, humanMessage(err, m.sentinel, m.fallback))
			return
		}
	}
	zap.S().Errorw("httpapi: internal error", "err", err)
	writeAPIError(w, http.StatusInternalServerError, "internal", "internal error: "+err.Error())
}

func writeAPIError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{"code": code, "message": message}})
}

func humanMessage(err, sentinel error, fallback string) string {
	msg := strings.TrimSuffix(err.Error(), ": "+sentinel.Error())
	if msg == "" || msg == sentinel.Error() {
		return fallback
	}
	return msg
}

func unauthorized(w http.ResponseWriter) {
	writeError(w, domain.ErrUnauthorized)
}

func decode(r *http.Request, v any) error {
	err := json.NewDecoder(r.Body).Decode(v)
	switch {
	case err == nil:
		return nil
	case errors.Is(err, io.EOF):
		return domain.Invalid("request body is required")
	default:
		return domain.Invalid("invalid JSON body: " + err.Error())
	}
}

func decodeOptional(r *http.Request, v any) error {
	if err := json.NewDecoder(r.Body).Decode(v); err != nil && !errors.Is(err, io.EOF) {
		return domain.Invalid("invalid JSON body: " + err.Error())
	}
	return nil
}

func pathID(r *http.Request) (int64, error) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		return 0, domain.Invalid("id in path must be an integer")
	}
	return id, nil
}

func queryID(r *http.Request, name string) (*int64, error) {
	q := r.URL.Query().Get(name)
	if q == "" {
		return nil, nil
	}
	id, err := strconv.ParseInt(q, 10, 64)
	if err != nil {
		return nil, domain.Invalid(name + " must be an integer")
	}
	return &id, nil
}

func found[T any](v *T, err error) (*T, error) {
	if err != nil {
		return nil, err
	}
	if v == nil {
		return nil, domain.ErrNotFound
	}
	return v, nil
}

func mapSlice[T, D any](in []T, f func(T) D) []D {
	out := make([]D, len(in))
	for i, v := range in {
		out[i] = f(v)
	}
	return out
}

// Logging — одна строка на запрос; 5xx — ERROR; /healthz не шумит.
func Logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" {
			next.ServeHTTP(w, r)
			return
		}
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(sw, r)
		fields := []any{"method", r.Method, "path", r.URL.Path, "status", sw.status,
			"duration_ms", time.Since(start).Milliseconds(), "remote", r.RemoteAddr}
		if sw.status >= 500 {
			zap.S().Errorw("http", fields...)
		} else {
			zap.S().Infow("http", fields...)
		}
	})
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (s *statusWriter) WriteHeader(code int) {
	s.status = code
	s.ResponseWriter.WriteHeader(code)
}

func (s *statusWriter) Flush() {
	if f, ok := s.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func (s *statusWriter) Unwrap() http.ResponseWriter { return s.ResponseWriter }

// Recover — паника хендлера → 500 в wire-формате вместо оборванного соединения.
func Recover(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if p := recover(); p != nil {
				if p == http.ErrAbortHandler {
					panic(p)
				}
				zap.S().Errorw("httpapi: panic", "method", r.Method, "path", r.URL.Path, "panic", p, "stack", string(debug.Stack()))
				writeAPIError(w, http.StatusInternalServerError, "internal", fmt.Sprintf("internal error: panic: %v", p))
			}
		}()
		next.ServeHTTP(w, r)
	})
}
