package httpapi

import (
	"crypto/subtle"
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// Реестр Раннеров (тикет 004).

type runnerDTO struct {
	ID              int64     `json:"id"`
	Name            string    `json:"name"`
	Address         string    `json:"address"`
	Slots           int       `json:"slots"`
	LastHeartbeatAt time.Time `json:"lastHeartbeatAt"`
}

func (s *Server) runnerAuth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		got := r.Header.Get("X-Runner-Token")
		if subtle.ConstantTimeCompare([]byte(got), []byte(s.RunnerToken)) != 1 {
			unauthorized(w)
			return
		}
		next(w, r)
	}
}

// GET /api/runners.
func (s *Server) listRunners(w http.ResponseWriter, r *http.Request) error {
	list, err := s.Store.Runners(r.Context())
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(list, func(run domain.Runner) runnerDTO { return runnerDTO(run) }))
}

// POST /api/runners.
func (s *Server) registerRunner(w http.ResponseWriter, r *http.Request) error {
	var req struct {
		Name    string `json:"name"`
		Address string `json:"address"`
		Slots   int    `json:"slots"`
	}
	if err := decode(r, &req); err != nil || req.Name == "" || req.Address == "" || req.Slots < 1 {
		return domain.Invalid("name, address and slots >= 1 are required")
	}
	id, err := s.Store.Upsert(r.Context(), domain.Runner{Name: req.Name, Address: req.Address, Slots: req.Slots})
	if err != nil {
		return err
	}
	run, err := found(s.Store.Runner(r.Context(), id))
	if err != nil {
		return err
	}
	return respond(w, http.StatusCreated, runnerDTO(*run))
}

// POST /api/runners/{id}/heartbeat.
func (s *Server) runnerHeartbeat(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	ok, err := s.Store.Heartbeat(r.Context(), id)
	if err != nil {
		return err
	}
	if !ok {
		return domain.ErrNotFound
	}
	return noContent(w)
}
