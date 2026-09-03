package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// BuildsHandler — CRUD Сборок Агентов.
type BuildsHandler struct {
	Store       domain.BuildStore
	Connections domain.ConnectionStore
}

type buildInput struct {
	Name                string          `json:"name"`
	LlmConnectionID     int64           `json:"llmConnectionId"`
	SandboxConnectionID int64           `json:"sandboxConnectionId"`
	Prompt              *string         `json:"prompt"`
	MemoryPreset        *string         `json:"memoryPreset"`
	Limits              json.RawMessage `json:"limits"`
	IsDefault           bool            `json:"isDefault"`
}

// Ключи limits, которые читает раннер (agent/core/lead/graph.py::_lead_features).
// Неизвестные ключи пропускаем как есть — forward-compat.
var knownLimitKeys = []string{"maxSubagents", "maxTotalSubagents", "subagentTimeout", "queueTimeout", "tokenBudget"}

func (in *buildInput) validate(w http.ResponseWriter) bool {
	if in.Name == "" {
		errorJSON(w, http.StatusBadRequest, "name is required")
		return false
	}
	if len(in.Limits) > 0 {
		var m map[string]any
		if err := json.Unmarshal(in.Limits, &m); err != nil {
			errorJSON(w, http.StatusBadRequest, "limits must be a JSON object")
			return false
		}
		for _, k := range knownLimitKeys {
			v, ok := m[k]
			if !ok {
				continue
			}
			if n, isNum := v.(float64); !isNum || n <= 0 {
				errorJSON(w, http.StatusBadRequest, "limits."+k+" must be a positive number")
				return false
			}
		}
	}
	return true
}

func (in *buildInput) toDomain(userID int64) *domain.AgentBuild {
	return &domain.AgentBuild{
		UserID: userID, Name: in.Name,
		LlmConnectionID: in.LlmConnectionID, SandboxConnectionID: in.SandboxConnectionID,
		Prompt: in.Prompt, MemoryPreset: in.MemoryPreset, Limits: in.Limits, IsDefault: in.IsDefault,
	}
}

// applyDefaults: пустые подключения → первое (новейшее) подключение пользователя,
// лимиты — недостающие ключи из domain.DefaultLimits. Без единого подключения — 400.
func (h *BuildsHandler) applyDefaults(w http.ResponseWriter, r *http.Request, b *domain.AgentBuild) bool {
	if b.LlmConnectionID == 0 {
		list, err := h.Connections.LlmConnections(r.Context(), b.UserID)
		if err != nil {
			writeError(w, r, err)
			return false
		}
		if len(list) == 0 {
			errorJSON(w, http.StatusBadRequest, "llmConnectionId is required: no llm connections to default to")
			return false
		}
		b.LlmConnectionID = list[0].ID
	}
	if b.SandboxConnectionID == 0 {
		list, err := h.Connections.SandboxConnections(r.Context())
		if err != nil {
			writeError(w, r, err)
			return false
		}
		if len(list) == 0 {
			errorJSON(w, http.StatusBadRequest, "sandboxConnectionId is required: no sandbox connections to default to")
			return false
		}
		b.SandboxConnectionID = list[0].ID
	}
	b.ApplyDefaults()
	return true
}

// List — GET /api/builds.
func (h *BuildsHandler) List(w http.ResponseWriter, r *http.Request) {
	list, err := h.Store.Builds(r.Context(), userID(r))
	if err != nil {
		writeError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(list, toBuildDTO))
}

// Create — POST /api/builds.
func (h *BuildsHandler) Create(w http.ResponseWriter, r *http.Request) {
	var in buildInput
	if !decodeBody(w, r, &in) || !in.validate(w) {
		return
	}
	b := in.toDomain(userID(r))
	if !h.applyDefaults(w, r, b) {
		return
	}
	if !b.IsDefault { // первая Сборка пользователя — дефолтная: иначе репо без подписки некому обслуживать
		existing, err := h.Store.Builds(r.Context(), b.UserID)
		if err != nil {
			writeError(w, r, err)
			return
		}
		b.IsDefault = len(existing) == 0
	}
	id, err := h.Store.CreateBuild(r.Context(), b)
	if err != nil {
		writeError(w, r, err)
		return
	}
	b.ID = id
	writeJSON(w, http.StatusCreated, toBuildDTO(*b))
}

// Patch — PATCH /api/builds/{id}.
func (h *BuildsHandler) Patch(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var in buildInput
	if !decodeBody(w, r, &in) || !in.validate(w) {
		return
	}
	b := in.toDomain(userID(r))
	b.ID = id
	if !h.applyDefaults(w, r, b) {
		return
	}
	if err := h.Store.UpdateBuild(r.Context(), b); err != nil {
		writeError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, toBuildDTO(*b))
}

// Delete — DELETE /api/builds/{id}; Сборка с Экземплярами/Репозиториями — 409.
func (h *BuildsHandler) Delete(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	if err := h.Store.DeleteBuild(r.Context(), id, userID(r)); err != nil {
		writeError(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
