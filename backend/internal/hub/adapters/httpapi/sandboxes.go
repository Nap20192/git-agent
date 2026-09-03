package httpapi

import (
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// Экземпляры Сэндбоксов.

type sandboxInstanceDTO struct {
	ID                  int64      `json:"id"`
	ExternalID          string     `json:"externalId"`
	SandboxConnectionID int64      `json:"sandboxConnectionId"`
	Status              string     `json:"status"`
	CreatedAt           time.Time  `json:"createdAt"`
	KilledAt            *time.Time `json:"killedAt"`
}

// GET /api/sandbox-instances.
func (s *Server) listSandboxInstances(w http.ResponseWriter, r *http.Request) error {
	list, err := s.Store.SandboxInstances(r.Context())
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(list, func(si domain.SandboxInstance) sandboxInstanceDTO {
		return sandboxInstanceDTO(si)
	}))
}

// POST /api/sandbox-instances.
func (s *Server) createSandboxInstance(w http.ResponseWriter, r *http.Request) error {
	var req struct {
		SandboxConnectionID int64 `json:"sandboxConnectionId"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	si, err := s.Sandboxes.Create(r.Context(), req.SandboxConnectionID)
	if err != nil {
		return err
	}
	return respond(w, http.StatusCreated, sandboxInstanceDTO(*si))
}

// DELETE /api/sandbox-instances/{id}.
func (s *Server) killSandboxInstance(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	if err := s.Sandboxes.Kill(r.Context(), id); err != nil {
		return err
	}
	return noContent(w)
}

// POST /api/instances/{id}/sandbox.
func (s *Server) linkInstanceSandbox(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	var req struct {
		SandboxInstanceID int64 `json:"sandboxInstanceId"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	if err := s.Store.LinkInstanceSandbox(r.Context(), id, req.SandboxInstanceID, userID(r)); err != nil {
		return err
	}
	return noContent(w)
}
