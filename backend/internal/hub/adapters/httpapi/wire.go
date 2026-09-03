package httpapi

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"runtime/debug"
	"strings"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
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

// errStatus — маппинг доменных сентинелов на HTTP: статус, wire-код и текст
// по умолчанию, если обёртка не сказала ничего осмысленного.
var errStatus = []struct {
	sentinel       error
	status         int
	code, fallback string
}{
	{domain.ErrInvalid, http.StatusBadRequest, "bad_request", "invalid request"},
	{domain.ErrUnauthorized, http.StatusUnauthorized, "unauthorized", "unauthorized"},
	{domain.ErrNotFound, http.StatusNotFound, "not_found", "not found"},
	{domain.ErrConflict, http.StatusConflict, "conflict", "conflict"},
	{domain.ErrUpstream, http.StatusBadGateway, "upstream", "upstream service failed"},
	{domain.ErrUnavailable, http.StatusServiceUnavailable, "unavailable", "provider is not configured (set *_OAUTH_CLIENT_ID/SECRET in .env)"},
	{domain.ErrTimeout, http.StatusGatewayTimeout, "timeout", "runner did not start streaming in time (queued too long)"},
}

// writeError — единая точка ошибок наружу: {"error":{"code","message"}}
// (backend/docs/openapi.yaml, зеркало frontend ApiError). Сентинел даёт
// статус, текст обёртки (fmt.Errorf("…: %w", ErrX)) — сообщение; всё
// неизвестное — 500 с текстом ошибки и записью в лог.
func writeError(w http.ResponseWriter, err error) {
	for _, m := range errStatus {
		if errors.Is(err, m.sentinel) {
			writeAPIError(w, m.status, m.code, humanMessage(err, m.sentinel, m.fallback))
			return
		}
	}
	slog.Error("httpapi: internal error", "err", err)
	writeAPIError(w, http.StatusInternalServerError, "internal", "internal error: "+err.Error())
}

func writeAPIError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{"code": code, "message": message}})
}

func badRequest(w http.ResponseWriter, message string) {
	writeAPIError(w, http.StatusBadRequest, "bad_request", message)
}

// humanMessage — текст ошибки без хвоста-сентинела («…: conflict»);
// голый сентинел без обёртки → fallback.
func humanMessage(err, sentinel error, fallback string) string {
	msg := strings.TrimSuffix(err.Error(), ": "+sentinel.Error())
	if msg == "" || msg == sentinel.Error() {
		return fallback
	}
	return msg
}

func decodeBody(w http.ResponseWriter, r *http.Request, v any) bool {
	err := json.NewDecoder(r.Body).Decode(v)
	switch {
	case err == nil:
		return true
	case errors.Is(err, io.EOF):
		badRequest(w, "request body is required")
	default:
		badRequest(w, "invalid JSON body: "+err.Error())
	}
	return false
}

// Logging — одна строка на запрос: метод, путь, статус, длительность; 5xx —
// уровнем ERROR (причина уже в логе writeError/Recover), /healthz не шумит.
func Logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" {
			next.ServeHTTP(w, r)
			return
		}
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(sw, r)
		level := slog.LevelInfo
		if sw.status >= 500 {
			level = slog.LevelError
		}
		slog.Log(r.Context(), level, "http",
			"method", r.Method, "path", r.URL.Path, "status", sw.status,
			"duration_ms", time.Since(start).Milliseconds(), "remote", r.RemoteAddr)
	})
}

// statusWriter — перехват статуса; Flush пробрасывается (SSE), Unwrap — для http.ResponseController.
type statusWriter struct {
	http.ResponseWriter
	status int
}

func (s *statusWriter) WriteHeader(code int) {
	s.status = code
	s.ResponseWriter.WriteHeader(code)
}

func (s *statusWriter) Flush() {
	if f, ok := s.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func (s *statusWriter) Unwrap() http.ResponseWriter { return s.ResponseWriter }

// Recover — паника хендлера → 500 в wire-формате вместо оборванного
// соединения (net/http сам паники глотает и просто закрывает коннект).
func Recover(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if p := recover(); p != nil {
				if p == http.ErrAbortHandler {
					panic(p)
				}
				slog.Error("httpapi: panic", "method", r.Method, "path", r.URL.Path, "panic", p, "stack", string(debug.Stack()))
				writeAPIError(w, http.StatusInternalServerError, "internal", fmt.Sprintf("internal error: panic: %v", p))
			}
		}()
		next.ServeHTTP(w, r)
	})
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
