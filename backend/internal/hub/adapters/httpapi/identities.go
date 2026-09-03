package httpapi

import (
	"log/slog"
	"net/http"
	"strconv"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// IdentitiesHandler — связки пользователя + прокси списка репозиториев провайдера.
type IdentitiesHandler struct {
	Store    domain.IdentityStore
	Provider domain.ProviderClient
	Secrets  *secrets.Box
}

func pathID(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		http.Error(w, `{"error":"bad id"}`, http.StatusBadRequest)
		return 0, false
	}
	return id, true
}

// List — GET /api/identities.
func (h *IdentitiesHandler) List(w http.ResponseWriter, r *http.Request) {
	list, err := h.Store.Identities(r.Context(), userID(r))
	if err != nil {
		writeError(w, err)
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
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// Repos — GET /api/identities/{id}/repos: прокси API провайдера
// по расшифрованному токену связки.
func (h *IdentitiesHandler) Repos(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	ident, err := h.Store.Identity(r.Context(), id, userID(r))
	if err != nil {
		writeError(w, err)
		return
	}
	if ident == nil {
		writeError(w, domain.ErrNotFound)
		return
	}
	token, err := h.Secrets.Decrypt(ident.AccessTokenEnc)
	if err != nil {
		writeError(w, err)
		return
	}
	repos, err := h.Provider.Repos(r.Context(), ident.Provider, string(token))
	if err != nil {
		slog.Error("identities: provider repos failed", "identityId", id, "err", err)
		http.Error(w, `{"error":"provider unavailable"}`, http.StatusBadGateway)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(repos, func(p domain.ProviderRepo) providerRepoDTO {
		return providerRepoDTO(p)
	}))
}
