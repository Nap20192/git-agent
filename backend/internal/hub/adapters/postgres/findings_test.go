package postgres

import (
	"context"
	"testing"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
)

// Находка v2 (миграция 007): раннер пишет напрямую в БД теми же именами колонок,
// hub читает через Store.Findings; фильтры и скоуп Репозитория.
func TestFindingsV2RoundTrip(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	store := &Store{Pool: db}
	repo, builds := seedRepo(t, db, 2)

	inst1, err := store.UpsertInstance(ctx, builds[0], repo.ID)
	if err != nil {
		t.Fatal(err)
	}
	inst2, err := store.UpsertInstance(ctx, builds[1], repo.ID)
	if err != nil {
		t.Fatal(err)
	}
	var eventID int64
	if err := db.QueryRow(ctx, `INSERT INTO hub.events (repository_id, provider, delivery_id, action, payload)
		VALUES ($1, 'github', 'd-1', 'push', '{}') RETURNING id`, repo.ID).Scan(&eventID); err != nil {
		t.Fatal(err)
	}
	blameDate := time.Date(2026, 9, 4, 10, 30, 0, 0, time.UTC)
	// так пишет раннер (hub_store.add_finding) — все v2-колонки
	if _, err := db.Exec(ctx, `INSERT INTO hub.findings
		(instance_id, severity, cwe, cve, file, line_start, line_end, evidence, remediation,
		 title, description, impact, confidence, category, "references",
		 blame_author, blame_email, blame_commit, blame_date, blame_commit_message, introduced_by, event_id)
		VALUES ($1, 'high', 'CWE-89', NULL, 'db.go', 10, 12, 'ev', 'fix',
		 'SQLi', 'desc', 'imp', 'high', 'injection', '["https://cwe.mitre.org/89"]',
		 'Ann', 'ann@x', 'abcdef0123456789', $2, 'add query', 'this_event', $3)`,
		inst1, blameDate, eventID); err != nil {
		t.Fatal(err)
	}
	// старая Находка (v1, только базовые поля) у второго Экземпляра
	if _, err := db.Exec(ctx, `INSERT INTO hub.findings (instance_id, severity) VALUES ($1, 'low')`, inst2); err != nil {
		t.Fatal(err)
	}

	list, err := store.Findings(ctx, domain.FindingFilter{InstanceID: &inst1})
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 1 {
		t.Fatalf("instance findings: %d, want 1", len(list))
	}
	f := list[0]
	switch {
	case *f.Title != "SQLi", *f.Description != "desc", *f.Impact != "imp", *f.Confidence != "high",
		*f.Category != "injection", string(f.References) != `["https://cwe.mitre.org/89"]`,
		*f.BlameAuthor != "Ann", *f.BlameEmail != "ann@x", *f.BlameCommit != "abcdef0123456789",
		!f.BlameDate.Equal(blameDate), *f.BlameCommitMessage != "add query", *f.IntroducedBy != "this_event",
		*f.EventID != eventID, *f.CWE != "CWE-89", f.CVE != nil, *f.LineStart != 10, *f.LineEnd != 12:
		t.Errorf("round-trip mismatch: %+v", f)
	}

	// сводно по репо — обе; v1-строка с NULL-полями читается
	all, err := store.Findings(ctx, domain.FindingFilter{RepositoryID: &repo.ID})
	if err != nil || len(all) != 2 {
		t.Fatalf("repository findings: %d %v, want 2", len(all), err)
	}
	if v1 := all[0]; v1.InstanceID != inst2 || v1.Title != nil || v1.References != nil {
		t.Errorf("v1 row: %+v", v1)
	}

	s := func(v string) *string { return &v }
	for name, tc := range map[string]struct {
		f    domain.FindingFilter
		want int
	}{
		"severity":     {domain.FindingFilter{RepositoryID: &repo.ID, Severity: s("high")}, 1},
		"category":     {domain.FindingFilter{RepositoryID: &repo.ID, Category: s("injection")}, 1},
		"eventId":      {domain.FindingFilter{RepositoryID: &repo.ID, EventID: &eventID}, 1},
		"introducedBy": {domain.FindingFilter{RepositoryID: &repo.ID, IntroducedBy: s("earlier")}, 0},
		"combo-miss":   {domain.FindingFilter{InstanceID: &inst1, Severity: s("low")}, 0},
	} {
		got, err := store.Findings(ctx, tc.f)
		if err != nil || len(got) != tc.want {
			t.Errorf("%s: %d %v, want %d", name, len(got), err, tc.want)
		}
	}

	// reports.structured — jsonb как есть; NULL у старых
	if _, err := db.Exec(ctx, `INSERT INTO hub.reports (instance_id, summary, structured) VALUES ($1, 'old', NULL),
		($1, 'new', '{"summary":"s","findingsBySeverity":{"high":1}}')`, inst1); err != nil {
		t.Fatal(err)
	}
	reports, err := store.Reports(ctx, inst1)
	if err != nil || len(reports) != 2 {
		t.Fatalf("reports: %d %v", len(reports), err)
	}
	if string(reports[0].Structured) != `{"summary": "s", "findingsBySeverity": {"high": 1}}` || reports[1].Structured != nil {
		t.Errorf("structured: %q / %q", reports[0].Structured, reports[1].Structured)
	}
}
