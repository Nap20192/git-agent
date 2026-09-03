package httpapi

import (
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// Подключённые Репозитории.

const eventsPageLimit = 100

type repositoryDTO struct {
	ID            int64     `json:"id"`
	IdentityID    int64     `json:"identityId"`
	Provider      string    `json:"provider"`
	ExternalID    string    `json:"externalId"`
	Owner         string    `json:"owner"`
	Name          string    `json:"name"`
	DefaultBranch *string   `json:"defaultBranch"`
	BuildID       *int64    `json:"buildId"`
	ConnectedAt   time.Time `json:"connectedAt"`
}

func toRepositoryDTO(r domain.Repository) repositoryDTO {
	return repositoryDTO{
		ID: r.ID, IdentityID: r.IdentityID, Provider: r.Provider, ExternalID: r.ExternalID,
		Owner: r.Owner, Name: r.Name, DefaultBranch: r.DefaultBranch,
		BuildID: r.BuildID, ConnectedAt: r.ConnectedAt,
	}
}

type eventDTO struct {
	ID         int64     `json:"id"`
	Provider   string    `json:"provider"`
	Action     string    `json:"action"`
	CommitSHA  *string   `json:"commitSha"`
	Ref        *string   `json:"ref"`
	ReceivedAt time.Time `json:"receivedAt"`
	TraceID    string    `json:"traceId"`
}

type triggerResultDTO struct {
	CommitSHA   string  `json:"commitSha"`
	Duplicate   bool    `json:"duplicate"`
	InstanceIDs []int64 `json:"instanceIds"`
}

func (s *Server) ownRepo(r *http.Request) (int64, error) {
	id, err := pathID(r)
	if err != nil {
		return 0, err
	}
	if _, err := found(s.Store.Repository(r.Context(), id, userID(r))); err != nil {
		return 0, err
	}
	return id, nil
}

// GET /api/repositories.
func (s *Server) listRepositories(w http.ResponseWriter, r *http.Request) error {
	list, err := s.Store.Repositories(r.Context(), userID(r))
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(list, toRepositoryDTO))
}

// POST /api/repositories.
func (s *Server) connectRepository(w http.ResponseWriter, r *http.Request) error {
	var req struct {
		IdentityID int64  `json:"identityId"`
		ExternalID string `json:"externalId"`
		BuildID    *int64 `json:"buildId"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	if req.IdentityID == 0 || req.ExternalID == "" {
		return domain.Invalid("identityId and externalId are required")
	}
	repo, err := s.Repositories.Connect(r.Context(), userID(r), req.IdentityID, req.ExternalID, req.BuildID)
	if err != nil {
		return err
	}
	return respond(w, http.StatusCreated, toRepositoryDTO(*repo))
}

// PATCH /api/repositories/{id}.
func (s *Server) patchRepository(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	var req struct {
		BuildID *int64 `json:"buildId"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	if req.BuildID == nil {
		return domain.Invalid("deprecated route: manage subscriptions via /api/repositories/{id}/subscriptions")
	}
	repo, err := s.Repositories.SetBuild(r.Context(), id, userID(r), *req.BuildID)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, toRepositoryDTO(*repo))
}

// DELETE /api/repositories/{id}.
func (s *Server) disconnectRepository(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	if err := s.Repositories.Disconnect(r.Context(), id, userID(r)); err != nil {
		return err
	}
	return noContent(w)
}

// POST /api/repositories/{id}/trigger.
func (s *Server) triggerRepository(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	var req struct {
		Ref       string `json:"ref"`
		CommitSHA string `json:"commitSha"`
		Mode      string `json:"mode"`
	}
	if err := decodeOptional(r, &req); err != nil {
		return err
	}
	if req.Mode != "" && req.Mode != "manual" && req.Mode != "full" {
		return domain.Invalid("mode must be manual or full")
	}
	res, err := s.Repositories.Trigger(r.Context(), userID(r), id, req.Ref, req.CommitSHA, req.Mode)
	if err != nil {
		return err
	}
	return respond(w, http.StatusAccepted, triggerResultDTO{
		CommitSHA:   res.CommitSHA,
		Duplicate:   res.Duplicate,
		InstanceIDs: append([]int64{}, res.InstanceIDs...), // [] вместо null в JSON
	})
}

// GET /api/repositories/{id}/events.
func (s *Server) repositoryEvents(w http.ResponseWriter, r *http.Request) error {
	id, err := s.ownRepo(r)
	if err != nil {
		return err
	}
	events, err := s.Store.Events(r.Context(), id, eventsPageLimit)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(events, func(e domain.EventRecord) eventDTO { return eventDTO(e) }))
}
