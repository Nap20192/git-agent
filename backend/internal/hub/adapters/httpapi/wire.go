// Package httpapi — inbound-адаптер HTTP (wire-формат backend/docs/openapi.yaml).
package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"

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

type errorDTO struct {
	Error string `json:"error"`
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

func writeError(w http.ResponseWriter, err error) {
	var invalid *domain.ValidationError
	switch {
	case errors.As(err, &invalid):
		writeJSON(w, http.StatusBadRequest, errorDTO{invalid.Msg})
	case errors.Is(err, domain.ErrNotFound):
		writeJSON(w, http.StatusNotFound, errorDTO{"not found"})
	case errors.Is(err, domain.ErrConflict):
		writeJSON(w, http.StatusConflict, errorDTO{"conflict"})
	case errors.Is(err, domain.ErrUnavailable):
		writeJSON(w, http.StatusServiceUnavailable, errorDTO{"provider is not configured (set *_OAUTH_CLIENT_ID/SECRET in .env)"})
	case errors.Is(err, domain.ErrTimeout):
		writeJSON(w, http.StatusGatewayTimeout, errorDTO{"runner did not start streaming in time (queued too long)"})
	case errors.Is(err, domain.ErrUpstream):
		zap.S().Warnw("httpapi: upstream error", "err", err)
		writeJSON(w, http.StatusBadGateway, errorDTO{"provider unavailable"})
	default:
		zap.S().Errorw("httpapi: internal error", "err", err)
		writeJSON(w, http.StatusInternalServerError, errorDTO{"internal"})
	}
}

func unauthorized(w http.ResponseWriter) {
	writeJSON(w, http.StatusUnauthorized, errorDTO{"unauthorized"})
}

func decode(r *http.Request, v any) error {
	if err := json.NewDecoder(r.Body).Decode(v); err != nil {
		return domain.Invalid("bad json")
	}
	return nil
}

func decodeOptional(r *http.Request, v any) error {
	if err := json.NewDecoder(r.Body).Decode(v); err != nil && !errors.Is(err, io.EOF) {
		return domain.Invalid("bad json")
	}
	return nil
}

func pathID(r *http.Request) (int64, error) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		return 0, domain.Invalid("bad id")
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
		return nil, domain.Invalid("bad " + name)
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
