package httpapi

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// LLM/sandbox-подключения.

type llmConnectionDTO struct {
	ID           int64           `json:"id"`
	Name         string          `json:"name"`
	APIBase      string          `json:"apiBase"`
	APIKeyMasked string          `json:"apiKeyMasked"`
	Model        string          `json:"model"`
	Params       json.RawMessage `json:"params"` // LlmParams (openapi); {} = дефолты провайдера
}

func (s *Server) toLlmConnectionDTO(c domain.LlmConnection) llmConnectionDTO {
	params := json.RawMessage(c.Params)
	if len(params) == 0 {
		params = json.RawMessage(`{}`)
	}
	return llmConnectionDTO{
		ID: c.ID, Name: c.Name, APIBase: c.APIBase,
		APIKeyMasked: s.Connections.MaskedKey(c.APIKeyEnc), Model: c.Model, Params: params,
	}
}

// llmParams — тело params: JSON-объект с известными ключами нужных типов; неизвестные
// верхнеуровневые ключи — 400 (опечатка молча ничего не сделает), extra — свободный объект.
func llmParams(raw json.RawMessage) ([]byte, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return []byte(`{}`), nil
	}
	var m map[string]any
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, domain.Invalid("params must be a JSON object")
	}
	for k, v := range m {
		switch k {
		case "temperature", "topP", "maxTokens", "contextWindow", "timeoutSeconds", "maxRetries":
			if _, ok := v.(float64); !ok && v != nil {
				return nil, domain.Invalid("params." + k + " must be a number")
			}
		case "reasoningEffort":
			if _, ok := v.(string); !ok && v != nil {
				return nil, domain.Invalid("params.reasoningEffort must be a string")
			}
		case "extra":
			if _, ok := v.(map[string]any); !ok && v != nil {
				return nil, domain.Invalid("params.extra must be an object")
			}
		default:
			return nil, domain.Invalid("params: unknown key " + k)
		}
		if v == nil {
			delete(m, k)
		}
	}
	return json.Marshal(m)
}

type llmConnectionReq struct {
	Name    string          `json:"name"`
	APIBase string          `json:"apiBase"`
	APIKey  string          `json:"apiKey"`
	Model   string          `json:"model"`
	Params  json.RawMessage `json:"params"`
}

func (q *llmConnectionReq) trim() {
	q.Name, q.APIBase = strings.TrimSpace(q.Name), strings.TrimSpace(q.APIBase)
	q.APIKey, q.Model = strings.TrimSpace(q.APIKey), strings.TrimSpace(q.Model)
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
	var req llmConnectionReq
	if err := decode(r, &req); err != nil {
		return err
	}
	req.trim()
	params, err := llmParams(req.Params)
	if err != nil {
		return err
	}
	c := &domain.LlmConnection{UserID: userID(r), Name: req.Name, APIBase: req.APIBase, Model: req.Model, Params: params}
	c.ApplyDefaults(s.Defaults) // apiBase/model → LLM_API_BASE/LLM_MODEL из .env
	if req.Name == "" || req.APIKey == "" || c.APIBase == "" || c.Model == "" {
		return domain.Invalid("name and apiKey are required; apiBase/model may be empty only with LLM_API_BASE/LLM_MODEL in .env")
	}
	id, err := s.Connections.CreateLlm(r.Context(), c, req.APIKey)
	if err != nil {
		return err
	}
	c.ID = id
	return respond(w, http.StatusCreated, s.toLlmConnectionDTO(*c))
}

// PUT /api/connections/llm/{id} — name/apiBase/model/params; apiKey пустой = не менять.
func (s *Server) updateLlmConnection(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	cur, err := found(s.Store.LlmConnection(r.Context(), id, userID(r)))
	if err != nil {
		return err
	}
	var req llmConnectionReq
	if err := decode(r, &req); err != nil {
		return err
	}
	req.trim()
	params, err := llmParams(req.Params)
	if err != nil {
		return err
	}
	c := &domain.LlmConnection{ID: id, UserID: userID(r), Name: req.Name, APIBase: req.APIBase, Model: req.Model, Params: params}
	c.ApplyDefaults(s.Defaults)
	if c.Name == "" || c.APIBase == "" || c.Model == "" {
		return domain.Invalid("name, apiBase and model are required")
	}
	if err := s.Connections.UpdateLlm(r.Context(), c, req.APIKey); err != nil {
		return err
	}
	c.APIKeyEnc = cur.APIKeyEnc
	if req.APIKey != "" {
		c.APIKeyEnc, _ = s.Connections.Secrets.Encrypt([]byte(req.APIKey))
	}
	return respond(w, http.StatusOK, s.toLlmConnectionDTO(*c))
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
	if req.Name == "" {
		return domain.Invalid("name is required")
	}
	var apiKey string
	if req.APIKey != nil {
		apiKey = strings.TrimSpace(*req.APIKey)
	}
	if apiKey == "" {
		apiKey = s.Defaults.SandboxAPIKey // OPENSANDBOX_API_KEY
	}
	if req.Image != nil {
		if img := strings.TrimSpace(*req.Image); img == "" {
			req.Image = nil
		} else {
			req.Image = &img
		}
	}
	c := &domain.SandboxConnection{Name: req.Name, Domain: req.Domain, Image: req.Image}
	c.ApplyDefaults(s.Defaults) // domain → OPENSANDBOX_DOMAIN, image → SANDBOX_IMAGE
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

// GET /api/defaults — чем hub заполняет пустые поля при создании (зеркало .env),
// чтобы формы фронта показывали их заранее; ключ не отдаём, только факт наличия.
func (s *Server) getDefaults(w http.ResponseWriter, _ *http.Request) error {
	return respond(w, http.StatusOK, map[string]any{
		"llmApiBase":       s.Defaults.LlmAPIBase,
		"llmModel":         s.Defaults.LlmModel,
		"sandboxDomain":    s.Defaults.SandboxDomain,
		"sandboxImage":     s.Defaults.SandboxImage,
		"sandboxApiKeySet": s.Defaults.SandboxAPIKey != "",
		"limits":           domain.DefaultLimits,
	})
}
