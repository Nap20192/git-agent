package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
)

func ptr[T any](v T) *T { return &v }

func itoa(v int64) string { return strconv.FormatInt(v, 10) }

var nasty = domain.Finding{
	ID: 1, Severity: "high", Title: ptr(`Quote "x", comma`), Category: ptr("injection"),
	File: ptr("a/b.go"), LineStart: ptr(3), LineEnd: ptr(5), CWE: ptr("CWE-89"), CVE: ptr("CVE-2024-1"),
	Confidence: ptr("high"), Remediation: ptr("line1\nline2 | pipe"),
	BlameAuthor: ptr("Ann"), BlameCommit: ptr("abcdef0123456789"), IntroducedBy: ptr("this_event"),
	BlameDate: ptr(time.Date(2026, 9, 4, 10, 30, 0, 0, time.UTC)),
}

func TestExportCSV(t *testing.T) {
	var buf bytes.Buffer
	if err := writeFindingsCSV(&buf, []domain.Finding{nasty, {ID: 2, Severity: "info"}}); err != nil {
		t.Fatal(err)
	}
	want := "\uFEFF#,severity,title,category,file:lines,introduced by,cwe/cve,confidence,remediation\r\n" +
		"1,high,\"Quote \"\"x\"\", comma\",injection,a/b.go:3-5,\"Ann @ 2026-09-04, abcdef0, this event\",CWE-89 / CVE-2024-1,high,\"line1\r\nline2 | pipe\"\r\n" + // перевод строки внутри поля — тоже CRLF (RFC 4180)
		"2,info,,,,,,,\r\n"
	if buf.String() != want {
		t.Errorf("csv:\n%q\nwant\n%q", buf.String(), want)
	}
}

func TestExportMarkdown(t *testing.T) {
	var buf bytes.Buffer
	if err := writeFindingsMarkdown(&buf, []domain.Finding{nasty}); err != nil {
		t.Fatal(err)
	}
	want := "| # | severity | title | category | file:lines | introduced by | cwe/cve | confidence | remediation |\n" +
		"| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n" +
		"| 1 | high | Quote \"x\", comma | injection | a/b.go:3-5 | Ann @ 2026-09-04, abcdef0, this event | CWE-89 / CVE-2024-1 | high | line1<br>line2 \\| pipe |\n"
	if buf.String() != want {
		t.Errorf("md:\n%s\nwant\n%s", buf.String(), want)
	}
}

func TestSortBySeverity(t *testing.T) {
	list := []domain.Finding{{ID: 1, Severity: "low"}, {ID: 2, Severity: "weird"}, {ID: 3, Severity: "critical"}, {ID: 4, Severity: "low"}}
	sortBySeverity(list)
	got := [4]int64{list[0].ID, list[1].ID, list[2].ID, list[3].ID}
	if got != [4]int64{3, 1, 4, 2} {
		t.Errorf("order: %v", got)
	}
}

// Роуты: фильтры, экспорт (заголовки, BOM, 400 на чужой format), сводка по репо.
func TestFindingsRoutes(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	var userID, repoID, buildID, instID int64
	if err := db.QueryRow(ctx, `
		WITH u AS (INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id),
		l AS (INSERT INTO hub.llm_connections (user_id, name, api_base, api_key_enc, model) SELECT id, 'l', 'http://x', '\x00', 'm' FROM u RETURNING id),
		s AS (INSERT INTO hub.sandbox_connections (name, domain) VALUES ('s', 'x') RETURNING id),
		b AS (INSERT INTO hub.agent_builds (user_id, name, llm_connection_id, sandbox_connection_id)
		      SELECT u.id, 'b', l.id, s.id FROM u, l, s RETURNING id, user_id),
		r AS (INSERT INTO hub.repositories (user_id, mode, provider, external_id, owner, name)
		      SELECT id, 'watch', 'github', '1', 'acme', 'repo' FROM u RETURNING id)
		INSERT INTO hub.agent_instances (build_id, repository_id, thread_id)
		SELECT b.id, r.id, 't' FROM b, r RETURNING build_id, repository_id, id, (SELECT user_id FROM b)`,
	).Scan(&buildID, &repoID, &instID, &userID); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(ctx, `INSERT INTO hub.findings (instance_id, severity, title, category, introduced_by)
		VALUES ($1, 'high', 'A', 'injection', 'this_event'), ($1, 'low', 'B', 'config', 'earlier')`, instID); err != nil {
		t.Fatal(err)
	}
	store := &pgstore.Store{Pool: db}
	srv := httptest.NewServer(NewMux(&Server{Store: store, DevUserID: userID}))
	defer srv.Close()

	get := func(path string) (*http.Response, string) {
		t.Helper()
		resp, err := http.Get(srv.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		body, _ := io.ReadAll(resp.Body)
		return resp, string(body)
	}
	titles := func(body string) []string {
		var list []struct {
			Title string `json:"title"`
		}
		_ = json.Unmarshal([]byte(body), &list)
		out := make([]string, len(list))
		for i, f := range list {
			out[i] = f.Title
		}
		return out
	}

	for path, want := range map[string]string{
		"/api/instances/%d/findings":                         "B,A",
		"/api/instances/%d/findings?severity=high":           "A",
		"/api/instances/%d/findings?category=config":         "B",
		"/api/instances/%d/findings?introducedBy=this_event": "A",
		"/api/instances/%d/findings?eventId=999":             "",
	} {
		resp, body := get(strings.Replace(path, "%d", itoa(instID), 1))
		if got := strings.Join(titles(body), ","); resp.StatusCode != 200 || got != want {
			t.Errorf("%s: %d %q, want %q", path, resp.StatusCode, got, want)
		}
	}
	if resp, body := get("/api/repositories/" + itoa(repoID) + "/findings?severity=low"); resp.StatusCode != 200 || strings.Join(titles(body), ",") != "B" {
		t.Errorf("repo findings: %d %s", resp.StatusCode, body)
	}
	if resp, _ := get("/api/instances/" + itoa(instID) + "/findings?eventId=x"); resp.StatusCode != 400 {
		t.Errorf("bad eventId: %d", resp.StatusCode)
	}

	resp, body := get("/api/repositories/" + itoa(repoID) + "/findings/export?format=csv")
	if resp.StatusCode != 200 || resp.Header.Get("Content-Disposition") != `attachment; filename="findings-repository-`+itoa(repoID)+`.csv"` ||
		!strings.HasPrefix(resp.Header.Get("Content-Type"), "text/csv") || !strings.HasPrefix(body, "\uFEFF#,severity") ||
		!strings.Contains(body, "\r\n1,high,A,") || !strings.Contains(body, "\r\n2,low,B,") {
		t.Errorf("csv export: %d %v %q", resp.StatusCode, resp.Header, body)
	}
	resp, body = get("/api/instances/" + itoa(instID) + "/findings/export?format=md&severity=low")
	if resp.StatusCode != 200 || !strings.HasSuffix(resp.Header.Get("Content-Disposition"), `.md"`) ||
		!strings.Contains(body, "| 1 | low | B | config |") || strings.Contains(body, "| A |") {
		t.Errorf("md export: %d %v %q", resp.StatusCode, resp.Header, body)
	}
	if resp, _ := get("/api/instances/" + itoa(instID) + "/findings/export?format=xml"); resp.StatusCode != 400 {
		t.Errorf("bad format: %d", resp.StatusCode)
	}
	if resp, _ := get("/api/instances/" + itoa(instID+1) + "/findings/export?format=csv"); resp.StatusCode != 404 {
		t.Errorf("unknown instance: %d", resp.StatusCode)
	}
}
