package httpapi

import (
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// OAuth-связки пользователя + прокси списка репозиториев провайдера.

type identityDTO struct {
	ID        int64     `json:"id"`
	Provider  string    `json:"provider"`
	Username  string    `json:"username"`
	CreatedAt time.Time `json:"createdAt"`
}

func toIdentityDTO(i domain.Identity) identityDTO {
	return identityDTO{ID: i.ID, Provider: i.Provider, Username: i.Username, CreatedAt: i.CreatedAt}
}

type providerRepoDTO struct {
	ExternalID    string  `json:"externalId"`
	Owner         string  `json:"owner"`
	Name          string  `json:"name"`
	DefaultBranch *string `json:"defaultBranch"`
	Private       bool    `json:"private"`
}

// GET /api/identities.
func (s *Server) listIdentities(w http.ResponseWriter, r *http.Request) error {
	list, err := s.Store.Identities(r.Context(), userID(r))
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(list, toIdentityDTO))
}

// DELETE /api/identities/{id}.
func (s *Server) deleteIdentity(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	if err := s.Store.DeleteIdentity(r.Context(), id, userID(r)); err != nil {
		return err
	}
	return noContent(w)
}

// GET /api/identities/{id}/repos.
func (s *Server) identityRepos(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	repos, err := s.Repositories.ProviderRepos(r.Context(), userID(r), id)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(repos, func(p domain.ProviderRepo) providerRepoDTO {
		return providerRepoDTO(p)
	}))
}
