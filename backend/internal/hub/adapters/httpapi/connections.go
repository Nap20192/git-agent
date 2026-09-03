package httpapi

import (
	"net/http"
	"strings"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// LLM/sandbox-подключения.

type llmConnectionDTO struct {
	ID           int64  `json:"id"`
	Name         string `json:"name"`
	APIBase      string `json:"apiBase"`
	APIKeyMasked string `json:"apiKeyMasked"`
	Model        string `json:"model"`
}

func (s *Server) toLlmConnectionDTO(c domain.LlmConnection) llmConnectionDTO {
	return llmConnectionDTO{
		ID: c.ID, Name: c.Name, APIBase: c.APIBase,
		APIKeyMasked: s.Connections.MaskedKey(c.APIKeyEnc), Model: c.Model,
	}
}

type sandboxConnectionDTO struct {
	ID           int64   `json:"id"`
	Name         string  `json:"name"`
	Domain       string  `json:"domain"`
	APIKeyMasked *string `json:"apiKeyMasked"`
	Image        *string `json:"image"`
}

func (s *Server) toSandboxConnectionDTO(c domain.SandboxConnection) sandboxConnectionDTO {
	var masked *string
	if c.APIKeyEnc != nil {
		m := s.Connections.MaskedKey(c.APIKeyEnc)
		masked = &m
	}
	return sandboxConnectionDTO{ID: c.ID, Name: c.Name, Domain: c.Domain, APIKeyMasked: masked, Image: c.Image}
}

// GET /api/connections/llm.
func (s *Server) listLlmConnections(w http.ResponseWriter, r *http.Request) error {
	list, err := s.Store.LlmConnections(r.Context(), userID(r))
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(list, s.toLlmConnectionDTO))
}

// POST /api/connections/llm.
func (s *Server) createLlmConnection(w http.ResponseWriter, r *http.Request) error {
	var req struct {
		Name    string `json:"name"`
		APIBase string `json:"apiBase"`
		APIKey  string `json:"apiKey"`
		Model   string `json:"model"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	req.Name, req.APIBase = strings.TrimSpace(req.Name), strings.TrimSpace(req.APIBase)
	req.APIKey, req.Model = strings.TrimSpace(req.APIKey), strings.TrimSpace(req.Model)
	if req.Name == "" || req.APIBase == "" || req.APIKey == "" || req.Model == "" {
		return domain.Invalid("name, apiBase, apiKey and model are required")
	}
	c := &domain.LlmConnection{UserID: userID(r), Name: req.Name, APIBase: req.APIBase, Model: req.Model}
	id, err := s.Connections.CreateLlm(r.Context(), c, req.APIKey)
	if err != nil {
		return err
	}
	c.ID = id
	return respond(w, http.StatusCreated, s.toLlmConnectionDTO(*c))
}

// DELETE /api/connections/llm/{id}.
func (s *Server) deleteLlmConnection(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	if err := s.Store.DeleteLlmConnection(r.Context(), id, userID(r)); err != nil {
		return err
	}
	return noContent(w)
}

// GET /api/connections/sandbox.
func (s *Server) listSandboxConnections(w http.ResponseWriter, r *http.Request) error {
	list, err := s.Store.SandboxConnections(r.Context())
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(list, s.toSandboxConnectionDTO))
}

// POST /api/connections/sandbox.
func (s *Server) createSandboxConnection(w http.ResponseWriter, r *http.Request) error {
	var req struct {
		Name   string  `json:"name"`
		Domain string  `json:"domain"`
		APIKey *string `json:"apiKey"`
		Image  *string `json:"image"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	req.Name, req.Domain = strings.TrimSpace(req.Name), strings.TrimSpace(req.Domain)
	if req.Name == "" || req.Domain == "" {
		return domain.Invalid("name and domain are required")
	}
	var apiKey string
	if req.APIKey != nil {
		apiKey = strings.TrimSpace(*req.APIKey)
	}
	if req.Image != nil {
		if img := strings.TrimSpace(*req.Image); img == "" {
			req.Image = nil
		} else {
			req.Image = &img
		}
	}
	c := &domain.SandboxConnection{Name: req.Name, Domain: req.Domain, Image: req.Image}
	id, err := s.Connections.CreateSandbox(r.Context(), c, apiKey)
	if err != nil {
		return err
	}
	c.ID = id
	return respond(w, http.StatusCreated, s.toSandboxConnectionDTO(*c))
}

// DELETE /api/connections/sandbox/{id}.
func (s *Server) deleteSandboxConnection(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	if err := s.Store.DeleteSandboxConnection(r.Context(), id); err != nil {
		return err
	}
	return noContent(w)
}
