package httpapi

import (
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// SubscriptionsHandler — подписки Сборок на события Репозитория (тикет 011).
type SubscriptionsHandler struct {
	Store domain.SubscriptionStore
	Repos domain.RepositoryAdmin
}

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

// ownRepo — Репозиторий пользователя либо 404.
func (h *SubscriptionsHandler) ownRepo(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, ok := pathID(w, r)
	if !ok {
		return 0, false
	}
	repo, err := h.Repos.Repository(r.Context(), id, userID(r))
	if err != nil {
		writeError(w, err)
		return 0, false
	}
	if repo == nil {
		writeError(w, domain.ErrNotFound)
		return 0, false
	}
	return id, true
}

// List — GET /api/repositories/{id}/subscriptions.
func (h *SubscriptionsHandler) List(w http.ResponseWriter, r *http.Request) {
	repoID, ok := h.ownRepo(w, r)
	if !ok {
		return
	}
	subs, err := h.Store.SubscriptionsByRepo(r.Context(), repoID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(subs, toSubscriptionDTO))
}

// Create — POST /api/repositories/{id}/subscriptions: upsert по (build, repo).
func (h *SubscriptionsHandler) Create(w http.ResponseWriter, r *http.Request) {
	repoID, ok := h.ownRepo(w, r)
	if !ok {
		return
	}
	var req struct {
		BuildID int64    `json:"buildId"`
		Actions []string `json:"actions"`
		RefMask *string  `json:"refMask"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if req.BuildID == 0 {
		badRequest(w, "buildId is required")
		return
	}
	sub := &domain.BuildSubscription{
		BuildID: req.BuildID, RepositoryID: repoID,
		Actions: req.Actions, RefMask: req.RefMask,
	}
	id, err := h.Store.UpsertSubscription(r.Context(), sub)
	if err != nil {
		writeError(w, err)
		return
	}
	sub.ID = id
	writeJSON(w, http.StatusCreated, toSubscriptionDTO(*sub))
}

// Delete — DELETE /api/subscriptions/{id}.
func (h *SubscriptionsHandler) Delete(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	if err := h.Store.DeleteSubscription(r.Context(), id, userID(r)); err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
