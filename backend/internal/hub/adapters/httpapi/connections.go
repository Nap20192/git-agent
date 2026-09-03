package httpapi

import (
	"net/http"
	"strings"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// ConnectionsHandler — LLM/sandbox-подключения.
// Инвариант redaction: ключи наружу ТОЛЬКО маской (MaskKey).
type ConnectionsHandler struct {
	Store    domain.ConnectionStore
	Secrets  *secrets.Box
	Defaults domain.Defaults
}

func (h *ConnectionsHandler) maskEnc(enc []byte) string {
	if enc == nil {
		return ""
	}
	key, err := h.Secrets.Decrypt(enc)
	if err != nil {
		return "…" // нерасшифровываемый ключ не повод отдать 500 на листинге
	}
	return MaskKey(string(key))
}

// ListLlm — GET /api/connections/llm.
func (h *ConnectionsHandler) ListLlm(w http.ResponseWriter, r *http.Request) {
	list, err := h.Store.LlmConnections(r.Context(), userID(r))
	if err != nil {
		writeError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(list, func(c domain.LlmConnection) llmConnectionDTO {
		return llmConnectionDTO{
			ID: c.ID, Name: c.Name, APIBase: c.APIBase,
			APIKeyMasked: h.maskEnc(c.APIKeyEnc), Model: c.Model,
		}
	}))
}

// CreateLlm — POST /api/connections/llm.
func (h *ConnectionsHandler) CreateLlm(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Name    string `json:"name"`
		APIBase string `json:"apiBase"`
		APIKey  string `json:"apiKey"`
		Model   string `json:"model"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	// TrimSpace: ' localhost:8090' в домене превращается в 'http://%20…' — чистим на входе
	req.Name, req.APIBase = strings.TrimSpace(req.Name), strings.TrimSpace(req.APIBase)
	req.APIKey, req.Model = strings.TrimSpace(req.APIKey), strings.TrimSpace(req.Model)
	c := &domain.LlmConnection{UserID: userID(r), Name: req.Name, APIBase: req.APIBase, Model: req.Model}
	c.ApplyDefaults(h.Defaults)
	if req.Name == "" || req.APIKey == "" || c.APIBase == "" || c.Model == "" {
		errorJSON(w, http.StatusBadRequest, "name and apiKey are required; apiBase/model may be empty only with LLM_API_BASE/LLM_MODEL in .env")
		return
	}
	enc, err := h.Secrets.Encrypt([]byte(req.APIKey))
	if err != nil {
		writeError(w, r, err)
		return
	}
	c.APIKeyEnc = enc
	id, err := h.Store.CreateLlmConnection(r.Context(), c)
	if err != nil {
		writeError(w, r, err)
		return
	}
	writeJSON(w, http.StatusCreated, llmConnectionDTO{
		ID: id, Name: c.Name, APIBase: c.APIBase, APIKeyMasked: MaskKey(req.APIKey), Model: c.Model,
	})
}

// DeleteLlm — DELETE /api/connections/llm/{id}; используется Сборкой — 409.
func (h *ConnectionsHandler) DeleteLlm(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	if err := h.Store.DeleteLlmConnection(r.Context(), id, userID(r)); err != nil {
		writeError(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ListSandbox — GET /api/connections/sandbox.
func (h *ConnectionsHandler) ListSandbox(w http.ResponseWriter, r *http.Request) {
	list, err := h.Store.SandboxConnections(r.Context())
	if err != nil {
		writeError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(list, func(c domain.SandboxConnection) sandboxConnectionDTO {
		var masked *string
		if c.APIKeyEnc != nil {
			m := h.maskEnc(c.APIKeyEnc)
			masked = &m
		}
		return sandboxConnectionDTO{ID: c.ID, Name: c.Name, Domain: c.Domain, APIKeyMasked: masked, Image: c.Image}
	}))
}

// CreateSandbox — POST /api/connections/sandbox.
func (h *ConnectionsHandler) CreateSandbox(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Name   string  `json:"name"`
		Domain string  `json:"domain"`
		APIKey *string `json:"apiKey"`
		Image  *string `json:"image"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	req.Name, req.Domain = strings.TrimSpace(req.Name), strings.TrimSpace(req.Domain)
	if req.APIKey != nil {
		*req.APIKey = strings.TrimSpace(*req.APIKey)
	}
	if req.Image != nil {
		*req.Image = strings.TrimSpace(*req.Image)
		if *req.Image == "" {
			req.Image = nil
		}
	}
	if req.Name == "" {
		errorJSON(w, http.StatusBadRequest, "name is required")
		return
	}
	c := &domain.SandboxConnection{Name: req.Name, Domain: req.Domain, Image: req.Image}
	c.ApplyDefaults(h.Defaults) // domain → OPENSANDBOX_DOMAIN, image → SANDBOX_IMAGE
	if (req.APIKey == nil || *req.APIKey == "") && h.Defaults.SandboxAPIKey != "" {
		key := h.Defaults.SandboxAPIKey // OPENSANDBOX_API_KEY
		req.APIKey = &key
	}
	var masked *string
	if req.APIKey != nil && *req.APIKey != "" {
		enc, err := h.Secrets.Encrypt([]byte(*req.APIKey))
		if err != nil {
			writeError(w, r, err)
			return
		}
		c.APIKeyEnc = enc
		m := MaskKey(*req.APIKey)
		masked = &m
	}
	id, err := h.Store.CreateSandboxConnection(r.Context(), c)
	if err != nil {
		writeError(w, r, err)
		return
	}
	writeJSON(w, http.StatusCreated, sandboxConnectionDTO{
		ID: id, Name: c.Name, Domain: c.Domain, APIKeyMasked: masked, Image: c.Image,
	})
}

// DeleteSandbox — DELETE /api/connections/sandbox/{id}.
func (h *ConnectionsHandler) DeleteSandbox(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	if err := h.Store.DeleteSandboxConnection(r.Context(), id); err != nil {
		writeError(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
