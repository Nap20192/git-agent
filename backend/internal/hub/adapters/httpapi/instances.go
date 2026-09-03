package httpapi

import (
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
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

// GET /api/instances/{id}/findings.
func (s *Server) instanceFindings(w http.ResponseWriter, r *http.Request) error {
	inst, err := s.instance(r)
	if err != nil {
		return err
	}
	findings, err := s.Store.Findings(r.Context(), inst.ID)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(findings, func(f domain.Finding) findingDTO { return findingDTO(f) }))
}
