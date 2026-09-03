package httpapi

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// Находки v2 (миграция 007): список с фильтрами и табличный экспорт (CSV/Markdown)
// по Экземпляру либо сводно по Репозиторию.

type findingDTO struct {
	ID                 int64           `json:"id"`
	InstanceID         int64           `json:"instanceId"`
	ReportID           *int64          `json:"reportId"`
	Severity           string          `json:"severity"`
	CWE                *string         `json:"cwe"`
	CVE                *string         `json:"cve"`
	File               *string         `json:"file"`
	LineStart          *int            `json:"lineStart"`
	LineEnd            *int            `json:"lineEnd"`
	Evidence           *string         `json:"evidence"`
	Remediation        *string         `json:"remediation"`
	CreatedAt          time.Time       `json:"createdAt"`
	Title              *string         `json:"title"`
	Description        *string         `json:"description"`
	Impact             *string         `json:"impact"`
	Confidence         *string         `json:"confidence"`
	Category           *string         `json:"category"`
	References         json.RawMessage `json:"references"`
	BlameAuthor        *string         `json:"blameAuthor"`
	BlameEmail         *string         `json:"blameEmail"`
	BlameCommit        *string         `json:"blameCommit"`
	BlameDate          *time.Time      `json:"blameDate"`
	BlameCommitMessage *string         `json:"blameCommitMessage"`
	IntroducedBy       *string         `json:"introducedBy"`
	EventID            *int64          `json:"eventId"`
}

// findingFilter — ?severity=&category=&eventId=&introducedBy= (скоуп ставит хендлер).
func findingFilter(r *http.Request) (domain.FindingFilter, error) {
	eventID, err := queryID(r, "eventId")
	if err != nil {
		return domain.FindingFilter{}, err
	}
	q := r.URL.Query()
	opt := func(name string) *string {
		if v := q.Get(name); v != "" {
			return &v
		}
		return nil
	}
	return domain.FindingFilter{
		Severity: opt("severity"), Category: opt("category"), EventID: eventID, IntroducedBy: opt("introducedBy"),
	}, nil
}

// GET /api/instances/{id}/findings.
func (s *Server) instanceFindings(w http.ResponseWriter, r *http.Request) error {
	f, err := s.instanceFindingFilter(r)
	if err != nil {
		return err
	}
	return s.listFindings(w, r, f)
}

// GET /api/instances/{id}/findings/export?format=csv|md.
func (s *Server) exportInstanceFindings(w http.ResponseWriter, r *http.Request) error {
	f, err := s.instanceFindingFilter(r)
	if err != nil {
		return err
	}
	return s.exportFindings(w, r, f, fmt.Sprintf("instance-%d", *f.InstanceID))
}

// GET /api/repositories/{id}/findings — сводно по всем Экземплярам Репозитория.
func (s *Server) repositoryFindings(w http.ResponseWriter, r *http.Request) error {
	f, err := s.repositoryFindingFilter(r)
	if err != nil {
		return err
	}
	return s.listFindings(w, r, f)
}

// GET /api/repositories/{id}/findings/export?format=csv|md.
func (s *Server) exportRepositoryFindings(w http.ResponseWriter, r *http.Request) error {
	f, err := s.repositoryFindingFilter(r)
	if err != nil {
		return err
	}
	return s.exportFindings(w, r, f, fmt.Sprintf("repository-%d", *f.RepositoryID))
}

func (s *Server) instanceFindingFilter(r *http.Request) (domain.FindingFilter, error) {
	inst, err := s.instance(r)
	if err != nil {
		return domain.FindingFilter{}, err
	}
	f, err := findingFilter(r)
	f.InstanceID = &inst.ID
	return f, err
}

func (s *Server) repositoryFindingFilter(r *http.Request) (domain.FindingFilter, error) {
	repoID, err := s.ownRepo(r)
	if err != nil {
		return domain.FindingFilter{}, err
	}
	f, err := findingFilter(r)
	f.RepositoryID = &repoID
	return f, err
}

func (s *Server) listFindings(w http.ResponseWriter, r *http.Request, f domain.FindingFilter) error {
	list, err := s.Store.Findings(r.Context(), f)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(list, func(f domain.Finding) findingDTO { return findingDTO(f) }))
}

func (s *Server) exportFindings(w http.ResponseWriter, r *http.Request, f domain.FindingFilter, name string) error {
	format := r.URL.Query().Get("format")
	if format != "csv" && format != "md" {
		return domain.Invalid("format must be csv or md")
	}
	list, err := s.Store.Findings(r.Context(), f)
	if err != nil {
		return err
	}
	sortBySeverity(list)
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="findings-%s.%s"`, name, format))
	if format == "csv" {
		w.Header().Set("Content-Type", "text/csv; charset=utf-8")
		return writeFindingsCSV(w, list)
	}
	w.Header().Set("Content-Type", "text/markdown; charset=utf-8")
	return writeFindingsMarkdown(w, list)
}

// ── табличный экспорт ────────────────────────────────────────────────────────

var exportHeader = []string{"#", "severity", "title", "category", "file:lines", "introduced by", "cwe/cve", "confidence", "remediation"}

var severityRank = map[string]int{"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

// sortBySeverity — critical → info, незнакомая severity в конец; внутри — порядок стора (новые сверху).
func sortBySeverity(list []domain.Finding) {
	rank := func(s string) int {
		if r, ok := severityRank[strings.ToLower(s)]; ok {
			return r
		}
		return len(severityRank)
	}
	slices.SortStableFunc(list, func(a, b domain.Finding) int { return rank(a.Severity) - rank(b.Severity) })
}

func exportRow(n int, f domain.Finding) []string {
	return []string{
		strconv.Itoa(n), f.Severity, str(f.Title), str(f.Category), fileLines(f),
		introducedBy(f), joinNonEmpty(" / ", str(f.CWE), str(f.CVE)), str(f.Confidence), str(f.Remediation),
	}
}

// writeFindingsCSV — RFC 4180 (CRLF, кавычки удваиваются) с UTF-8 BOM для Excel.
func writeFindingsCSV(w io.Writer, list []domain.Finding) error {
	if _, err := io.WriteString(w, "\uFEFF"); err != nil {
		return err
	}
	cw := csv.NewWriter(w)
	cw.UseCRLF = true
	if err := cw.Write(exportHeader); err != nil {
		return err
	}
	for i, f := range list {
		if err := cw.Write(exportRow(i+1, f)); err != nil {
			return err
		}
	}
	cw.Flush()
	return cw.Error()
}

// writeFindingsMarkdown — таблица; `|` экранируется, переводы строк → <br>.
func writeFindingsMarkdown(w io.Writer, list []domain.Finding) error {
	var b strings.Builder
	line := func(cells []string) {
		b.WriteString("|")
		for _, c := range cells {
			b.WriteString(" " + mdCell(c) + " |")
		}
		b.WriteString("\n")
	}
	line(exportHeader)
	b.WriteString("|" + strings.Repeat(" --- |", len(exportHeader)) + "\n")
	for i, f := range list {
		line(exportRow(i+1, f))
	}
	_, err := io.WriteString(w, b.String())
	return err
}

func mdCell(s string) string {
	s = strings.ReplaceAll(s, "|", `\|`)
	s = strings.ReplaceAll(s, "\r\n", "<br>")
	return strings.NewReplacer("\n", "<br>", "\r", "<br>").Replace(s)
}

func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func fileLines(f domain.Finding) string {
	if f.File == nil {
		return ""
	}
	out := *f.File
	if f.LineStart != nil {
		out += ":" + strconv.Itoa(*f.LineStart)
		if f.LineEnd != nil && *f.LineEnd != *f.LineStart {
			out += "-" + strconv.Itoa(*f.LineEnd)
		}
	}
	return out
}

// introducedBy — «author @ 2026-09-04, abc1234, this event».
func introducedBy(f domain.Finding) string {
	who := str(f.BlameAuthor)
	if f.BlameDate != nil {
		who = joinNonEmpty(" @ ", who, f.BlameDate.UTC().Format("2006-01-02"))
	}
	sha := str(f.BlameCommit)
	if len(sha) > 7 {
		sha = sha[:7]
	}
	return joinNonEmpty(", ", who, sha, strings.ReplaceAll(str(f.IntroducedBy), "_", " "))
}

func joinNonEmpty(sep string, parts ...string) string {
	return strings.Join(slices.DeleteFunc(parts, func(s string) bool { return s == "" }), sep)
}
