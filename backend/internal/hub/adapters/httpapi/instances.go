package httpapi

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"strings"
)

// Экземпляры Агентов.

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

type reportDTO struct {
	ID         int64           `json:"id"`
	InstanceID int64           `json:"instanceId"`
	EventID    *int64          `json:"eventId"`
	Summary    string          `json:"summary"`
	CreatedAt  time.Time       `json:"createdAt"`
	Structured json.RawMessage `json:"structured"` // ReportStructured (openapi); null у старых
	CommitSHA  *string         `json:"commitSha"`  // из События отчёта; null у отчётов чата
	Ref        *string         `json:"ref"`
	Action     *string         `json:"action"`
}

func (s *Server) instance(r *http.Request) (*domain.AgentInstance, error) {
	id, err := pathID(r)
	if err != nil {
		return nil, err
	}
	return found(s.Store.Instance(r.Context(), id, userID(r)))
}

// GET /api/instances[?repositoryId=].
func (s *Server) listInstances(w http.ResponseWriter, r *http.Request) error {
	repoID, err := queryID(r, "repositoryId")
	if err != nil {
		return err
	}
	list, err := s.Store.Instances(r.Context(), userID(r), repoID)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(list, func(i domain.AgentInstance) instanceDTO { return instanceDTO(i) }))
}

// GET /api/instances/{id}.
func (s *Server) getInstance(w http.ResponseWriter, r *http.Request) error {
	inst, err := s.instance(r)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, instanceDTO(*inst))
}

// GET /api/instances/{id}/reports.
func (s *Server) instanceReports(w http.ResponseWriter, r *http.Request) error {
	inst, err := s.instance(r)
	if err != nil {
		return err
	}
	reports, err := s.Store.Reports(r.Context(), inst.ID)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(reports, func(rep domain.Report) reportDTO { return reportDTO(rep) }))
}

// GET /api/instances/{id}/messages?before=&limit= — транскрипт чата Экземпляра
// (история как в ChatGPT: реплики + карточки ходов по Событиям), новые последними;
// more=true — есть страница старее: повторить с before=<id первой строки>.
func (s *Server) instanceMessages(w http.ResponseWriter, r *http.Request) error {
	inst, err := s.instance(r)
	if err != nil {
		return err
	}
	before, err := queryID(r, "before")
	if err != nil {
		return err
	}
	limit := int64(50)
	if l, err := queryID(r, "limit"); err != nil {
		return err
	} else if l != nil {
		limit = min(max(*l, 1), 200)
	}
	rows, err := s.Store.Messages(r.Context(), inst.ID, before, int32(limit))
	if err != nil {
		return err
	}
	out := make([]chatMessageDTO, 0, len(rows))
	for i := len(rows) - 1; i >= 0; i-- {
		out = append(out, toChatMessageDTO(rows[i]))
	}
	return respond(w, http.StatusOK, map[string]any{"messages": out, "more": int64(len(rows)) == limit})
}

// chatMessageDTO — ChatMessage из openapi.yaml: role=user|agent — реплика (text),
// role=event — карточка хода (status started|finished|failed, action/commitSha
// События, findingsCount; у упавшего хода чата action нет, text — причина).
type chatMessageDTO struct {
	ID            int64     `json:"id"`
	Role          string    `json:"role"`
	Text          string    `json:"text,omitempty"`
	EventID       *int64    `json:"eventId,omitempty"`
	Action        *string   `json:"action,omitempty"`
	CommitSHA     *string   `json:"commitSha,omitempty"`
	Status        string    `json:"status,omitempty"`
	FindingsCount *int      `json:"findingsCount,omitempty"`
	Ts            time.Time `json:"ts"`
	TraceID       string    `json:"traceId,omitempty"`
}

func toChatMessageDTO(m domain.ChatMessage) chatMessageDTO {
	var p struct {
		Text          string `json:"text"`
		Description   string `json:"description"`
		FindingsCount *int   `json:"findingsCount"`
	}
	_ = json.Unmarshal(m.Payload, &p)
	d := chatMessageDTO{ID: m.ID, EventID: m.EventID, Action: m.Action, CommitSHA: m.CommitSHA, Ts: m.CreatedAt, TraceID: m.TraceID}
	switch m.Kind {
	case "chat_user":
		d.Role, d.Text = "user", p.Text
	case "chat_agent":
		d.Role, d.Text = "agent", p.Text
	default:
		d.Role, d.Status, d.Text, d.FindingsCount = "event", strings.TrimPrefix(m.Kind, "run_"), p.Description, p.FindingsCount
	}
	return d
}
