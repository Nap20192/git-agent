package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"

	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

const eventsPageLimit = 100

// RepositoriesHandler — подключённые Репозитории и их журнал Событий.
type RepositoriesHandler struct {
	Store   domain.RepositoryAdmin
	Subs    domain.SubscriptionStore
	Service *app.RepositoryService
}

// List — GET /api/repositories.
func (h *RepositoriesHandler) List(w http.ResponseWriter, r *http.Request) {
	list, err := h.Store.Repositories(r.Context(), userID(r))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(list, toRepositoryDTO))
}

// Connect — POST /api/repositories: создаёт webhook у провайдера.
func (h *RepositoriesHandler) Connect(w http.ResponseWriter, r *http.Request) {
	var req struct {
		IdentityID int64  `json:"identityId"`
		ExternalID string `json:"externalId"`
		BuildID    *int64 `json:"buildId"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if req.IdentityID == 0 || req.ExternalID == "" {
		http.Error(w, `{"error":"identityId and externalId are required"}`, http.StatusBadRequest)
		return
	}
	repo, err := h.Service.Connect(r.Context(), userID(r), req.IdentityID, req.ExternalID, req.BuildID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, toRepositoryDTO(*repo))
}

// Patch — PATCH /api/repositories/{id}. Deprecated (тикет 011): привязка
// Сборок теперь подписками; {buildId} транслируется в подписку на все события.
func (h *RepositoriesHandler) Patch(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var req struct {
		BuildID *int64 `json:"buildId"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if req.BuildID == nil {
		http.Error(w, `{"error":"deprecated route: manage subscriptions via /api/repositories/{id}/subscriptions"}`,
			http.StatusBadRequest)
		return
	}
	repo, err := h.Store.Repository(r.Context(), id, userID(r))
	if err != nil {
		writeError(w, err)
		return
	}
	if repo == nil {
		writeError(w, domain.ErrNotFound)
		return
	}
	if _, err := h.Subs.UpsertSubscription(r.Context(), &domain.BuildSubscription{
		BuildID: *req.BuildID, RepositoryID: id,
	}); err != nil {
		writeError(w, err)
		return
	}
	repo, err = h.Store.Repository(r.Context(), id, userID(r))
	if err != nil || repo == nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, toRepositoryDTO(*repo))
}

// Disconnect — DELETE /api/repositories/{id}: снимает хук у провайдера.
func (h *RepositoriesHandler) Disconnect(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	if err := h.Service.Disconnect(r.Context(), id, userID(r)); err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// Trigger — POST /api/repositories/{id}/trigger: ручной запуск агента.
// Тело необязательно ({ref?, commitSha?}); пустое — HEAD default-ветки.
func (h *RepositoriesHandler) Trigger(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var req struct {
		Ref       string `json:"ref"`
		CommitSHA string `json:"commitSha"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil && !errors.Is(err, io.EOF) {
		http.Error(w, `{"error":"bad json"}`, http.StatusBadRequest)
		return
	}
	res, err := h.Service.Trigger(r.Context(), userID(r), id, req.Ref, req.CommitSHA)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusAccepted, triggerResultDTO{
		CommitSHA:   res.CommitSHA,
		Duplicate:   res.Duplicate,
		InstanceIDs: append([]int64{}, res.InstanceIDs...), // [] вместо null в JSON
	})
}

type triggerResultDTO struct {
	CommitSHA   string  `json:"commitSha"`
	Duplicate   bool    `json:"duplicate"`
	InstanceIDs []int64 `json:"instanceIds"`
}

// Events — GET /api/repositories/{id}/events.
func (h *RepositoriesHandler) Events(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	repo, err := h.Store.Repository(r.Context(), id, userID(r))
	if err != nil {
		writeError(w, err)
		return
	}
	if repo == nil {
		writeError(w, domain.ErrNotFound)
		return
	}
	events, err := h.Store.Events(r.Context(), id, eventsPageLimit)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(events, func(e domain.EventRecord) eventDTO {
		return eventDTO(e)
	}))
}
