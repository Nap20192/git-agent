package httpapi

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/logger"
)

// MaskKey — инвариант redaction (зеркало agent/infra/server/wire.py::mask_key):
// секрет наружу только маской.
func MaskKey(key string) string {
	if key == "" {
		return ""
	}
	if len(key) > 4 {
		return "…" + key[len(key)-4:]
	}
	return "…"
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		slog.Error("httpapi: encode response", "err", err)
	}
}

// errorJSON — единый формат ошибки наружу: {"error": msg} с правильным Content-Type.
func errorJSON(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// writeError — маппинг доменных ошибок в статус. Всё неизвестное — 500 с
// requestId в теле (для корреляции с логом) и записью в лог; обрыв клиента
// (context.Canceled) — не ошибка сервера.
func writeError(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, domain.ErrNotFound):
		errorJSON(w, http.StatusNotFound, "not found")
	case errors.Is(err, domain.ErrConflict):
		errorJSON(w, http.StatusConflict, "conflict")
	case errors.Is(err, domain.ErrUnavailable):
		// понятный текст: без OAuth-ключей провайдер недоступен, сервис жив
		errorJSON(w, http.StatusServiceUnavailable, "provider is not configured (set *_OAUTH_CLIENT_ID/SECRET in .env)")
	case errors.Is(err, domain.ErrUnauthorized):
		errorJSON(w, http.StatusBadGateway, "provider rejected the token (reconnect the identity)")
	case errors.Is(err, domain.ErrTimeout):
		errorJSON(w, http.StatusGatewayTimeout, "runner did not start streaming in time (queued too long)")
	case r.Context().Err() != nil:
		// клиент ушёл (или сервер гасится) — любая ошибка после этого не наша;
		// 499 — соглашение nginx, чтобы access-log не показывал status 0
		w.WriteHeader(statusClientClosedRequest)
	default:
		slog.ErrorContext(r.Context(), "httpapi: internal error", "err", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{
			"error": "internal", "requestId": logger.RequestID(r.Context()),
		})
	}
}

const statusClientClosedRequest = 499

// maxJSONBody — потолок JSON-тела API (вебхуки — свой лимит в webhook.go).
const maxJSONBody = 1 << 20

func decodeBody(w http.ResponseWriter, r *http.Request, v any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, maxJSONBody)
	if err := json.NewDecoder(r.Body).Decode(v); err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			errorJSON(w, http.StatusRequestEntityTooLarge, "body too large")
			return false
		}
		errorJSON(w, http.StatusBadRequest, "bad json")
		return false
	}
	return true
}

// ── DTO (camelCase — backend/docs/openapi.yaml) ─────────────────────────────

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

type repositoryDTO struct {
	ID            int64     `json:"id"`
	IdentityID    int64     `json:"identityId"`
	Provider      string    `json:"provider"`
	ExternalID    string    `json:"externalId"`
	Owner         string    `json:"owner"`
	Name          string    `json:"name"`
	DefaultBranch *string   `json:"defaultBranch"`
	BuildID       *int64    `json:"buildId"`
	ConnectedAt   time.Time `json:"connectedAt"`
}

func toRepositoryDTO(r domain.Repository) repositoryDTO {
	return repositoryDTO{
		ID: r.ID, IdentityID: r.IdentityID, Provider: r.Provider, ExternalID: r.ExternalID,
		Owner: r.Owner, Name: r.Name, DefaultBranch: r.DefaultBranch,
		BuildID: r.BuildID, ConnectedAt: r.ConnectedAt,
	}
}

type eventDTO struct {
	ID         int64     `json:"id"`
	Provider   string    `json:"provider"`
	Action     string    `json:"action"`
	CommitSHA  *string   `json:"commitSha"`
	Ref        *string   `json:"ref"`
	ReceivedAt time.Time `json:"receivedAt"`
}

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

type llmConnectionDTO struct {
	ID           int64  `json:"id"`
	Name         string `json:"name"`
	APIBase      string `json:"apiBase"`
	APIKeyMasked string `json:"apiKeyMasked"`
	Model        string `json:"model"`
}

type sandboxConnectionDTO struct {
	ID           int64   `json:"id"`
	Name         string  `json:"name"`
	Domain       string  `json:"domain"`
	APIKeyMasked *string `json:"apiKeyMasked"`
	Image        *string `json:"image"`
}

type instanceDTO struct {
	ID                int64     `json:"id"`
	BuildID           int64     `json:"buildId"`
	RepositoryID      int64     `json:"repositoryId"`
	SandboxInstanceID *int64    `json:"sandboxInstanceId"`
	SandboxExternalID *string   `json:"sandboxExternalId"`
	SandboxStatus     *string   `json:"sandboxStatus"`
	ThreadID          string    `json:"threadId"`
	Status            string    `json:"status"`
	RunnerID          *int64    `json:"runnerId"`
	UpdatedAt         time.Time `json:"updatedAt"`
}

func toInstanceDTO(i domain.AgentInstance) instanceDTO {
	return instanceDTO{
		ID: i.ID, BuildID: i.BuildID, RepositoryID: i.RepositoryID,
		SandboxInstanceID: i.SandboxInstanceID,
		SandboxExternalID: i.SandboxExternalID, SandboxStatus: i.SandboxStatus,
		ThreadID: i.ThreadID,
		Status:   i.Status, RunnerID: i.RunnerID, UpdatedAt: i.UpdatedAt,
	}
}

type sandboxInstanceDTO struct {
	ID                  int64      `json:"id"`
	ExternalID          string     `json:"externalId"`
	SandboxConnectionID int64      `json:"sandboxConnectionId"`
	Status              string     `json:"status"`
	CreatedAt           time.Time  `json:"createdAt"`
	KilledAt            *time.Time `json:"killedAt"`
}

func toSandboxInstanceDTO(si domain.SandboxInstance) sandboxInstanceDTO {
	return sandboxInstanceDTO(si)
}

type runnerDTO struct {
	ID              int64     `json:"id"`
	Name            string    `json:"name"`
	Address         string    `json:"address"`
	Slots           int       `json:"slots"`
	LastHeartbeatAt time.Time `json:"lastHeartbeatAt"`
}

type reportDTO struct {
	ID         int64     `json:"id"`
	InstanceID int64     `json:"instanceId"`
	EventID    *int64    `json:"eventId"`
	Summary    string    `json:"summary"`
	CreatedAt  time.Time `json:"createdAt"`
}

type findingDTO struct {
	ID          int64     `json:"id"`
	InstanceID  int64     `json:"instanceId"`
	ReportID    *int64    `json:"reportId"`
	Severity    string    `json:"severity"`
	CWE         *string   `json:"cwe"`
	CVE         *string   `json:"cve"`
	File        *string   `json:"file"`
	LineStart   *int      `json:"lineStart"`
	LineEnd     *int      `json:"lineEnd"`
	Evidence    *string   `json:"evidence"`
	Remediation *string   `json:"remediation"`
	CreatedAt   time.Time `json:"createdAt"`
}

// mapSlice — []domain → []DTO; пустой список сериализуется как [], не null.
func mapSlice[T, D any](in []T, f func(T) D) []D {
	out := make([]D, len(in))
	for i, v := range in {
		out[i] = f(v)
	}
	return out
}
