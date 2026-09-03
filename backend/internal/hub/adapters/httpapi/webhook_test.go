package httpapi

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
	"github.com/vnkjd/git-agent/backend/pkg/trace"
)

func githubSig(body []byte, secret string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return "sha256=" + hex.EncodeToString(mac.Sum(nil))
}

func TestParseEventGitHubPush(t *testing.T) {
	h := http.Header{}
	h.Set("X-GitHub-Delivery", "d-1")
	h.Set("X-GitHub-Event", "push")
	e, ok := parseEvent("github", h, []byte(`{"after":"abc123","ref":"refs/heads/main"}`))
	if !ok || e.DeliveryID != "d-1" || e.Action != "push" || e.CommitSHA != "abc123" || e.Ref != "refs/heads/main" {
		t.Errorf("got %+v ok=%v", e, ok)
	}
}

// Диапазон push: before + объединение added/modified/removed по коммитам без дублей.
func TestParseEventGitHubPushDiffContext(t *testing.T) {
	h := http.Header{}
	h.Set("X-GitHub-Delivery", "d-1")
	h.Set("X-GitHub-Event", "push")
	e, _ := parseEvent("github", h, []byte(`{"after":"abc","before":"000abc","ref":"refs/heads/main",
		"commits":[{"added":["a.go"],"modified":["b.go"],"removed":[]},{"modified":["b.go","c.go"],"removed":["d.go"]}]}`))
	if e.BeforeSHA != "000abc" || strings.Join(e.ChangedFiles, ",") != "a.go,b.go,c.go,d.go" {
		t.Errorf("got %+v", e)
	}
	// force-push / новая ветка — диапазона нет
	e, _ = parseEvent("github", h, []byte(`{"after":"abc","before":"000abc","forced":true}`))
	if e.BeforeSHA != "" {
		t.Errorf("forced: beforeSha %q", e.BeforeSHA)
	}
	e, _ = parseEvent("github", h, []byte(`{"after":"abc","before":"0000000000000000000000000000000000000000"}`))
	if e.BeforeSHA != "" || e.ChangedFiles != nil {
		t.Errorf("new branch: got %+v", e)
	}
}

func TestParseEventGitHubPullRequest(t *testing.T) {
	h := http.Header{}
	h.Set("X-GitHub-Delivery", "d-2")
	h.Set("X-GitHub-Event", "pull_request")
	longBody := strings.Repeat("я", domain.PRBodyMaxLen+10)
	e, ok := parseEvent("github", h, []byte(`{"pull_request":{"number":42,"title":"Fix auth","body":"`+longBody+`",
		"head":{"sha":"def456","ref":"feature"},"base":{"sha":"base789"}}}`))
	if !ok || e.CommitSHA != "def456" || e.Ref != "feature" || e.BaseSHA != "base789" || e.HeadSHA != "def456" ||
		e.PRNumber != 42 || e.PRTitle != "Fix auth" || len([]rune(e.PRBody)) != domain.PRBodyMaxLen || len(e.ChangedFiles) != 0 {
		t.Errorf("got %+v ok=%v", e, ok)
	}
}

func TestParseEventGitLabPush(t *testing.T) {
	h := http.Header{}
	h.Set("X-Gitlab-Event-UUID", "u-1")
	e, ok := parseEvent("gitlab", h, []byte(`{"object_kind":"push","checkout_sha":"abc","before":"bef","ref":"refs/heads/main",
		"commits":[{"added":["x.py"],"modified":[],"removed":["y.py"]}]}`))
	if !ok || e.Action != "push" || e.CommitSHA != "abc" || e.BeforeSHA != "bef" || strings.Join(e.ChangedFiles, ",") != "x.py,y.py" {
		t.Errorf("got %+v ok=%v", e, ok)
	}
}

func TestParseEventGitLabMergeRequest(t *testing.T) {
	h := http.Header{}
	h.Set("X-Gitlab-Event-UUID", "u-2")
	e, ok := parseEvent("gitlab", h,
		[]byte(`{"object_kind":"merge_request","object_attributes":{"iid":7,"title":"MR","description":"desc","source_branch":"feat",
			"last_commit":{"id":"c0ffee"},"diff_refs":{"base_sha":"b1","head_sha":"h1"}}}`))
	if !ok || e.CommitSHA != "c0ffee" || e.Ref != "feat" || e.BaseSHA != "b1" || e.HeadSHA != "h1" ||
		e.PRNumber != 7 || e.PRTitle != "MR" || e.PRBody != "desc" {
		t.Errorf("got %+v ok=%v", e, ok)
	}
	// без diff_refs — head = last_commit
	e, _ = parseEvent("gitlab", h,
		[]byte(`{"object_kind":"merge_request","object_attributes":{"source_branch":"feat","last_commit":{"id":"c0ffee"}}}`))
	if e.HeadSHA != "c0ffee" || e.BaseSHA != "" {
		t.Errorf("fallback: got %+v", e)
	}
}

func TestParseEventMissingDelivery(t *testing.T) {
	h := http.Header{}
	h.Set("X-GitHub-Event", "push")
	if _, ok := parseEvent("github", h, []byte(`{}`)); ok {
		t.Error("event without delivery id accepted")
	}
}

// --- интеграция: HTTP → app.WebhookService → postgres.Store ---------------

const hookSecret = "per-repo-secret"

// seed: user → identity → llm+sandbox connections → build → repository. Возвращает id репозитория.
func seed(t *testing.T, db *pgxpool.Pool, box *secrets.Box) int64 {
	t.Helper()
	enc, err := box.Encrypt([]byte(hookSecret))
	if err != nil {
		t.Fatal(err)
	}
	var repoID int64
	err = db.QueryRow(context.Background(), `
		WITH u AS (INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id),
		i AS (INSERT INTO hub.identities (user_id, provider, provider_user_id, username, access_token_enc)
		      SELECT id, 'github', 'gh-1', 't', '\x00' FROM u RETURNING id, user_id),
		l AS (INSERT INTO hub.llm_connections (user_id, name, api_base, api_key_enc, model)
		      SELECT id, 'llm', 'http://x', '\x00', 'm' FROM u RETURNING id, user_id),
		s AS (INSERT INTO hub.sandbox_connections (name, domain) VALUES ('sbx', 'localhost:8090') RETURNING id),
		b AS (INSERT INTO hub.agent_builds (user_id, name, llm_connection_id, sandbox_connection_id)
		      SELECT l.user_id, 'default', l.id, s.id FROM l, s RETURNING id, user_id),
		r AS (INSERT INTO hub.repositories (user_id, identity_id, provider, external_id, owner, name, webhook_secret_enc)
		      SELECT b.user_id, i.id, 'github', '100', 'acme', 'repo', $1 FROM b, i RETURNING id)
		INSERT INTO hub.build_subscriptions (build_id, repository_id)
		SELECT b.id, r.id FROM b, r
		RETURNING repository_id`, enc).Scan(&repoID)
	if err != nil {
		t.Fatal(err)
	}
	return repoID
}

func count(t *testing.T, db *pgxpool.Pool, query string, args ...any) int {
	t.Helper()
	var n int
	if err := db.QueryRow(context.Background(), query, args...).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

func TestWebhookIngest(t *testing.T) {
	db := testdb.Setup(t)
	box, _ := secrets.New(bytes.Repeat([]byte{1}, 32))
	repoID := seed(t, db, box)

	store := &pgstore.Store{Pool: db}
	srv := httptest.NewServer(Logging(NewMux(&Server{
		Webhook: &app.WebhookService{Repos: store, Subs: store, Ingestor: store, Secrets: box},
	})))
	defer srv.Close()

	body := []byte(`{"after":"abc123","before":"000111","ref":"refs/heads/main","commits":[{"added":["a.go"],"modified":["b.go"]}]}`)
	send := func(url, delivery, sig string) *http.Response {
		req, _ := http.NewRequest("POST", url, bytes.NewReader(body))
		req.Header.Set(trace.Header, "0123456789abcdef0123456789abcdef")
		req.Header.Set("X-GitHub-Delivery", delivery)
		req.Header.Set("X-GitHub-Event", "push")
		req.Header.Set("X-Hub-Signature-256", sig)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		return resp
	}
	hookURL := srv.URL + "/hooks/github/" + strconv.FormatInt(repoID, 10)
	goodSig := githubSig(body, hookSecret)

	// валидная доставка: событие + Экземпляр + журнал Экземпляра + outbox
	if resp := send(hookURL, "d-1", goodSig); resp.StatusCode != 200 {
		t.Fatalf("status %d", resp.StatusCode)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.events WHERE delivery_id = 'd-1' AND commit_sha = 'abc123'`); n != 1 {
		t.Fatalf("events: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.agent_instances WHERE repository_id = $1 AND status = 'down'`, repoID); n != 1 {
		t.Fatalf("instances: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.instance_events WHERE dedup_key = 'abc123' AND processed_at IS NULL`); n != 1 {
		t.Fatalf("instance_events: %d", n)
	}
	rk := "github." + strconv.FormatInt(repoID, 10) + ".push"
	if n := count(t, db, `SELECT count(*) FROM hub.outbox WHERE routing_key = $1 AND published_at IS NULL`, rk); n != 1 {
		t.Fatalf("outbox: %d", n)
	}
	// trace_id вебхука — в журнале События и в Rabbit-сообщении outbox
	const traceID = "0123456789abcdef0123456789abcdef"
	if n := count(t, db, `SELECT count(*) FROM hub.events WHERE delivery_id = 'd-1' AND trace_id = $1`, traceID); n != 1 {
		t.Fatalf("events.trace_id: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.outbox WHERE payload->>'traceId' = $1`, traceID); n != 1 {
		t.Fatalf("outbox traceId: %d", n)
	}
	// diff-контекст (миграция 006) — в журнале и в Rabbit-сообщении
	if n := count(t, db, `SELECT count(*) FROM hub.events WHERE delivery_id = 'd-1' AND before_sha = '000111'
		AND changed_files = '["a.go","b.go"]'::jsonb AND base_sha IS NULL AND pr_number IS NULL`); n != 1 {
		t.Fatalf("events diff context: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.outbox WHERE payload->>'beforeSha' = '000111'
		AND payload->'changedFiles' = '["a.go","b.go"]'::jsonb AND NOT payload ? 'baseSha'`); n != 1 {
		t.Fatalf("outbox diff context: %d", n)
	}

	// повтор той же доставки — no-op (дедуп по provider+delivery_id), но всё равно 200
	if resp := send(hookURL, "d-1", goodSig); resp.StatusCode != 200 {
		t.Fatalf("dup status %d", resp.StatusCode)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.events`); n != 1 {
		t.Fatalf("events after dup: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.outbox`); n != 1 {
		t.Fatalf("outbox after dup: %d", n)
	}

	// вторая доставка — Экземпляр остаётся один (upsert), outbox растёт
	send(hookURL, "d-2", goodSig)
	if n := count(t, db, `SELECT count(*) FROM hub.agent_instances`); n != 1 {
		t.Fatalf("instances after 2nd: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.outbox`); n != 2 {
		t.Fatalf("outbox after 2nd: %d", n)
	}

	// невалидная подпись и неизвестный репо: наружу 200, внутрь ничего
	if resp := send(hookURL, "d-3", githubSig(body, "wrong")); resp.StatusCode != 200 {
		t.Fatalf("bad sig status %d", resp.StatusCode)
	}
	if resp := send(srv.URL+"/hooks/github/999999", "d-4", goodSig); resp.StatusCode != 200 {
		t.Fatalf("unknown repo status %d", resp.StatusCode)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.events`); n != 2 {
		t.Fatalf("events after drops: %d", n)
	}
}

// Репо вовсе без подписок обслуживает дефолтная Сборка (тикет 011).
func TestWebhookDefaultBuildFallback(t *testing.T) {
	db := testdb.Setup(t)
	box, _ := secrets.New(bytes.Repeat([]byte{1}, 32))
	repoID := seed(t, db, box)
	ctx := context.Background()

	// сносим подписку и заводим дефолтную Сборку того же пользователя
	if _, err := db.Exec(ctx, `DELETE FROM hub.build_subscriptions`); err != nil {
		t.Fatal(err)
	}
	var defaultBuild int64
	if err := db.QueryRow(ctx, `
		INSERT INTO hub.agent_builds (user_id, name, llm_connection_id, sandbox_connection_id, is_default)
		SELECT user_id, 'fallback', llm_connection_id, sandbox_connection_id, true
		  FROM hub.agent_builds LIMIT 1
		RETURNING id`).Scan(&defaultBuild); err != nil {
		t.Fatal(err)
	}

	store := &pgstore.Store{Pool: db}
	srv := httptest.NewServer(NewMux(&Server{
		Webhook: &app.WebhookService{Repos: store, Subs: store, Ingestor: store, Secrets: box},
	}))
	defer srv.Close()

	body := []byte(`{"after":"abc","ref":"refs/heads/main"}`)
	req, _ := http.NewRequest("POST", srv.URL+"/hooks/github/"+strconv.FormatInt(repoID, 10), bytes.NewReader(body))
	req.Header.Set("X-GitHub-Delivery", "d-def")
	req.Header.Set("X-GitHub-Event", "push")
	req.Header.Set("X-Hub-Signature-256", githubSig(body, hookSecret))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()

	if n := count(t, db,
		`SELECT count(*) FROM hub.agent_instances WHERE build_id = $1`, defaultBuild); n != 1 {
		t.Fatalf("instances for default build: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.outbox`); n != 1 {
		t.Fatalf("outbox: %d", n)
	}
}
