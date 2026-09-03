package httpapi

import (
	"log/slog"
	"net/http"
	"strconv"

	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// IdentitiesHandler — связки пользователя + прокси списка репозиториев провайдера.
type IdentitiesHandler struct {
	Store    domain.IdentityStore
	Provider domain.ProviderClient
	Auth     *app.AuthService
}

func pathID(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		errorJSON(w, http.StatusBadRequest, "bad id")
		return 0, false
	}
	return id, true
}

// List — GET /api/identities.
func (h *IdentitiesHandler) List(w http.ResponseWriter, r *http.Request) {
	list, err := h.Store.Identities(r.Context(), userID(r))
	if err != nil {
		writeError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(list, toIdentityDTO))
}

// Delete — DELETE /api/identities/{id}; связка с Репозиториями — 409.
func (h *IdentitiesHandler) Delete(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	if err := h.Store.DeleteIdentity(r.Context(), id, userID(r)); err != nil {
		writeError(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// Repos — GET /api/identities/{id}/repos: прокси API провайдера токеном
// связки (401 от провайдера — refresh-флоу внутри CallWithToken).
func (h *IdentitiesHandler) Repos(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	ident, err := h.Store.Identity(r.Context(), id, userID(r))
	if err != nil {
		writeError(w, r, err)
		return
	}
	if ident == nil {
		writeError(w, r, domain.ErrNotFound)
		return
	}
	var repos []domain.ProviderRepo
	err = h.Auth.CallWithToken(r.Context(), ident, func(token string) error {
		var err error
		repos, err = h.Provider.Repos(r.Context(), ident.Provider, token)
		return err
	})
	if err != nil {
		slog.ErrorContext(r.Context(), "identities: provider repos failed", "identityId", id, "err", err)
		errorJSON(w, http.StatusBadGateway, "provider unavailable")
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(repos, func(p domain.ProviderRepo) providerRepoDTO {
		return providerRepoDTO(p)
	}))
}
