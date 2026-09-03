package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// BuildsHandler — CRUD Сборок Агентов.
type BuildsHandler struct {
	Store domain.BuildStore
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

func (in *buildInput) validate(w http.ResponseWriter) bool {
	if in.Name == "" || in.LlmConnectionID == 0 || in.SandboxConnectionID == 0 {
		http.Error(w, `{"error":"name, llmConnectionId and sandboxConnectionId are required"}`, http.StatusBadRequest)
		return false
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

// List — GET /api/builds.
func (h *BuildsHandler) List(w http.ResponseWriter, r *http.Request) {
	list, err := h.Store.Builds(r.Context(), userID(r))
	if err != nil {
		writeError(w, err)
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
	id, err := h.Store.CreateBuild(r.Context(), b)
	if err != nil {
		writeError(w, err)
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
	if err := h.Store.UpdateBuild(r.Context(), b); err != nil {
		writeError(w, err)
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
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
