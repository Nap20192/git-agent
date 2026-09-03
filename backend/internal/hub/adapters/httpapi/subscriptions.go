package httpapi

import (
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// Подписки Сборок на события Репозитория (тикет 011).

type subscriptionDTO struct {
	ID           int64     `json:"id"`
	BuildID      int64     `json:"buildId"`
	RepositoryID int64     `json:"repositoryId"`
	Actions      []string  `json:"actions"`
	RefMask      *string   `json:"refMask"`
	CreatedAt    time.Time `json:"createdAt"`
}

func toSubscriptionDTO(s domain.BuildSubscription) subscriptionDTO {
	actions := s.Actions
	if actions == nil {
		actions = []string{}
	}
	return subscriptionDTO{
		ID: s.ID, BuildID: s.BuildID, RepositoryID: s.RepositoryID,
		Actions: actions, RefMask: s.RefMask, CreatedAt: s.CreatedAt,
	}
}

// GET /api/repositories/{id}/subscriptions.
func (s *Server) listSubscriptions(w http.ResponseWriter, r *http.Request) error {
	id, err := s.ownRepo(r)
	if err != nil {
		return err
	}
	subs, err := s.Store.SubscriptionsByRepo(r.Context(), id)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(subs, toSubscriptionDTO))
}

// POST /api/repositories/{id}/subscriptions.
func (s *Server) createSubscription(w http.ResponseWriter, r *http.Request) error {
	id, err := s.ownRepo(r)
	if err != nil {
		return err
	}
	var req struct {
		BuildID int64    `json:"buildId"`
		Actions []string `json:"actions"`
		RefMask *string  `json:"refMask"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	if req.BuildID == 0 {
		return domain.Invalid("buildId is required")
	}
	sub := &domain.BuildSubscription{BuildID: req.BuildID, RepositoryID: id, Actions: req.Actions, RefMask: req.RefMask}
	if sub.ID, err = s.Store.UpsertSubscription(r.Context(), sub); err != nil {
		return err
	}
	return respond(w, http.StatusCreated, toSubscriptionDTO(*sub))
}

// DELETE /api/subscriptions/{id}.
func (s *Server) deleteSubscription(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	if err := s.Store.DeleteSubscription(r.Context(), id, userID(r)); err != nil {
		return err
	}
	return noContent(w)
}
