package httpapi

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// Сборки Агентов.

type buildDTO struct {
	ID                  int64           `json:"id"`
	Name                string          `json:"name"`
	LlmConnectionID     int64           `json:"llmConnectionId"`
	SandboxConnectionID int64           `json:"sandboxConnectionId"`
	Prompt              *string         `json:"prompt"`
	MemoryPreset        *string         `json:"memoryPreset"`
	Limits              json.RawMessage `json:"limits"`
	IsDefault           bool            `json:"isDefault"`
	CreatedAt           time.Time       `json:"createdAt"`
}

func toBuildDTO(b domain.AgentBuild) buildDTO {
	limits := json.RawMessage(b.Limits)
	if len(limits) == 0 {
		limits = json.RawMessage(`{}`)
	}
	return buildDTO{
		ID: b.ID, Name: b.Name,
		LlmConnectionID: b.LlmConnectionID, SandboxConnectionID: b.SandboxConnectionID,
		Prompt: b.Prompt, MemoryPreset: b.MemoryPreset, Limits: limits,
		IsDefault: b.IsDefault, CreatedAt: b.CreatedAt,
	}
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

var knownLimitKeys = []string{"maxSubagents", "maxTotalSubagents", "subagentTimeout", "queueTimeout", "tokenBudget"}

func (in *buildInput) validate() error {
	if in.Name == "" || in.LlmConnectionID == 0 || in.SandboxConnectionID == 0 {
		return domain.Invalid("name, llmConnectionId and sandboxConnectionId are required")
	}
	if len(in.Limits) == 0 {
		return nil
	}
	var m map[string]any
	if err := json.Unmarshal(in.Limits, &m); err != nil {
		return domain.Invalid("limits must be a JSON object")
	}
	for _, k := range knownLimitKeys {
		v, ok := m[k]
		if !ok {
			continue
		}
		if n, isNum := v.(float64); !isNum || n <= 0 {
			return domain.Invalid("limits." + k + " must be a positive number")
		}
	}
	return nil
}

func (in *buildInput) toDomain(userID int64) *domain.AgentBuild {
	return &domain.AgentBuild{
		UserID: userID, Name: in.Name,
		LlmConnectionID: in.LlmConnectionID, SandboxConnectionID: in.SandboxConnectionID,
		Prompt: in.Prompt, MemoryPreset: in.MemoryPreset, Limits: in.Limits, IsDefault: in.IsDefault,
	}
}

func decodeBuild(r *http.Request) (*domain.AgentBuild, error) {
	var in buildInput
	if err := decode(r, &in); err != nil {
		return nil, err
	}
	if err := in.validate(); err != nil {
		return nil, err
	}
	return in.toDomain(userID(r)), nil
}

// GET /api/builds.
func (s *Server) listBuilds(w http.ResponseWriter, r *http.Request) error {
	list, err := s.Store.Builds(r.Context(), userID(r))
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(list, toBuildDTO))
}

// POST /api/builds.
func (s *Server) createBuild(w http.ResponseWriter, r *http.Request) error {
	b, err := decodeBuild(r)
	if err != nil {
		return err
	}
	if b.ID, err = s.Store.CreateBuild(r.Context(), b); err != nil {
		return err
	}
	return respond(w, http.StatusCreated, toBuildDTO(*b))
}

// PATCH /api/builds/{id}.
func (s *Server) patchBuild(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	b, err := decodeBuild(r)
	if err != nil {
		return err
	}
	b.ID = id
	if err := s.Store.UpdateBuild(r.Context(), b); err != nil {
		return err
	}
	return respond(w, http.StatusOK, toBuildDTO(*b))
}

// DELETE /api/builds/{id}.
func (s *Server) deleteBuild(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	if err := s.Store.DeleteBuild(r.Context(), id, userID(r)); err != nil {
		return err
	}
	return noContent(w)
}
