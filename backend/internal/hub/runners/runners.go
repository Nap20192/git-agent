// Package runners — реестр раннеров (тикет 004): саморегистрация + heartbeat,
// оба роута за заголовком X-Runner-Token.
package runners

import (
	"crypto/subtle"
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct {
	DB    *pgxpool.Pool
	Token string
}

// Auth — middleware: constant-time сравнение X-Runner-Token с RUNNER_TOKEN.
func (h *Handler) Auth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		got := r.Header.Get("X-Runner-Token")
		if subtle.ConstantTimeCompare([]byte(got), []byte(h.Token)) != 1 {
			http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
			return
		}
		next(w, r)
	}
}

// Register — POST /api/runners: upsert по уникальному имени; повторная
// регистрация обновляет адрес/слоты и продлевает heartbeat.
func (h *Handler) Register(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Name    string `json:"name"`
		Address string `json:"address"`
		Slots   int    `json:"slots"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Name == "" || req.Address == "" || req.Slots < 1 {
		http.Error(w, `{"error":"name, address and slots >= 1 are required"}`, http.StatusBadRequest)
		return
	}
	var id int64
	err := h.DB.QueryRow(r.Context(),
		`INSERT INTO hub.runners (name, address, slots)
		 VALUES ($1, $2, $3)
		 ON CONFLICT (name) DO UPDATE
		   SET address = $2, slots = $3, last_heartbeat_at = now()
		 RETURNING id`,
		req.Name, req.Address, req.Slots,
	).Scan(&id)
	if err != nil {
		slog.Error("runners: register failed", "name", req.Name, "err", err)
		http.Error(w, `{"error":"internal"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{"id": id, "name": req.Name})
}

// Heartbeat — POST /api/runners/{id}/heartbeat.
func (h *Handler) Heartbeat(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		http.Error(w, `{"error":"bad id"}`, http.StatusBadRequest)
		return
	}
	tag, err := h.DB.Exec(r.Context(),
		`UPDATE hub.runners SET last_heartbeat_at = now() WHERE id = $1`, id)
	if err != nil {
		slog.Error("runners: heartbeat failed", "id", id, "err", err)
		http.Error(w, `{"error":"internal"}`, http.StatusInternalServerError)
		return
	}
	if tag.RowsAffected() == 0 {
		http.Error(w, `{"error":"unknown runner"}`, http.StatusNotFound)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
