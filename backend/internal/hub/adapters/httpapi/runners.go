package httpapi

import (
	"crypto/subtle"
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// RunnersHandler — реестр Раннеров (тикет 004): саморегистрация + heartbeat
// за заголовком X-Runner-Token; список — пользовательский (session).
type RunnersHandler struct {
	Store domain.RunnerStore
	Token string
}

// List — GET /api/runners (UI/отладка).
func (h *RunnersHandler) List(w http.ResponseWriter, r *http.Request) {
	list, err := h.Store.Runners(r.Context())
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(list, func(run domain.Runner) runnerDTO {
		return runnerDTO(run)
	}))
}

// Auth — middleware: constant-time сравнение X-Runner-Token с RUNNER_TOKEN.
func (h *RunnersHandler) Auth(next http.HandlerFunc) http.HandlerFunc {
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
// регистрация обновляет адрес/слоты и продлевает heartbeat. 201 + Runner.
func (h *RunnersHandler) Register(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Name    string `json:"name"`
		Address string `json:"address"`
		Slots   int    `json:"slots"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Name == "" || req.Address == "" || req.Slots < 1 {
		http.Error(w, `{"error":"name, address and slots >= 1 are required"}`, http.StatusBadRequest)
		return
	}
	id, err := h.Store.Upsert(r.Context(), domain.Runner{Name: req.Name, Address: req.Address, Slots: req.Slots})
	if err != nil {
		slog.Error("runners: register failed", "name", req.Name, "err", err)
		http.Error(w, `{"error":"internal"}`, http.StatusInternalServerError)
		return
	}
	run, err := h.Store.Runner(r.Context(), id)
	if err != nil || run == nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, runnerDTO(*run))
}

// Heartbeat — POST /api/runners/{id}/heartbeat.
func (h *RunnersHandler) Heartbeat(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		http.Error(w, `{"error":"bad id"}`, http.StatusBadRequest)
		return
	}
	ok, err := h.Store.Heartbeat(r.Context(), id)
	if err != nil {
		slog.Error("runners: heartbeat failed", "id", id, "err", err)
		http.Error(w, `{"error":"internal"}`, http.StatusInternalServerError)
		return
	}
	if !ok {
		http.Error(w, `{"error":"unknown runner"}`, http.StatusNotFound)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
