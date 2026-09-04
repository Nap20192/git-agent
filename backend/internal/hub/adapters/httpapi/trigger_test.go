package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/provider"
	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
	"github.com/vnkjd/git-agent/backend/pkg/trace"
)

// Ручной запуск (POST /api/repositories/{id}/trigger): тот же fan-out, что и
// вебхук — Событие action=manual + Экземпляр + outbox; повтор на том же
// коммите идемпотентен; репо без подписок обслуживает дефолтная Сборка.
func TestTrigger(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	box, _ := secrets.New(bytes.Repeat([]byte{1}, 32))
	repoID := seed(t, db, box)

	// seed кладёт нешифрованный токен и не задаёт default_branch — чиним
	var userID int64
	if err := db.QueryRow(ctx, `SELECT user_id FROM hub.repositories WHERE id = $1`, repoID).Scan(&userID); err != nil {
		t.Fatal(err)
	}
	tokEnc, _ := box.Encrypt([]byte("provider-token"))
	if _, err := db.Exec(ctx, `UPDATE hub.identities SET access_token_enc = $1`, tokEnc); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(ctx, `UPDATE hub.repositories SET default_branch = 'main' WHERE id = $1`, repoID); err != nil {
		t.Fatal(err)
	}

	// фейковый GitHub: HEAD default-ветки; провайдер получает X-Trace-Id запроса
	const traceID = "fedcba9876543210fedcba9876543210"
	var providerTrace string
	gh := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		providerTrace = r.Header.Get(trace.Header)
		if r.URL.Path != "/repos/acme/repo/commits/main" {
			http.NotFound(w, r)
			return
		}
		w.Write([]byte(`{"sha":"headsha"}`))
	}))
	defer gh.Close()

	store := &pgstore.Store{Pool: db}
	webhook := &app.WebhookService{Repos: store, Subs: store, Ingestor: store, Secrets: box}
	svc := &app.RepositoryService{
		Repos: store, Identities: store, Subs: store,
		Provider: &provider.Client{GitHubBase: gh.URL},
		Auth:     &app.AuthService{Store: store, Secrets: box},
		Webhook:  webhook, Secrets: box,
	}
	srv := httptest.NewServer(Logging(NewMux(&Server{Store: store, Repositories: svc, DevUserID: userID})))
	defer srv.Close()

	trigger := func(repoID int64, body string) (int, triggerResultDTO) {
		t.Helper()
		req, _ := http.NewRequest("POST", srv.URL+"/api/repositories/"+strconv.FormatInt(repoID, 10)+"/trigger",
			bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set(trace.Header, traceID)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		var res triggerResultDTO
		_ = json.NewDecoder(resp.Body).Decode(&res)
		return resp.StatusCode, res
	}

	// пустое тело: HEAD default-ветки через провайдера → Событие+Экземпляр+outbox
	status, res := trigger(repoID, "")
	if status != http.StatusAccepted || res.CommitSHA != "headsha" || res.Duplicate || len(res.InstanceIDs) != 1 {
		t.Fatalf("status=%d res=%+v", status, res)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.events WHERE action = 'manual' AND commit_sha = 'headsha'`); n != 1 {
		t.Fatalf("events: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.agent_instances WHERE repository_id = $1`, repoID); n != 1 {
		t.Fatalf("instances: %d", n)
	}
	rk := "github." + strconv.FormatInt(repoID, 10) + ".manual"
	if n := count(t, db, `SELECT count(*) FROM hub.outbox WHERE routing_key = $1`, rk); n != 1 {
		t.Fatalf("outbox: %d", n)
	}
	// trace_id запроса /trigger = trace_id События; провайдеру ушёл тот же заголовок
	if providerTrace != traceID {
		t.Fatalf("provider got trace %q", providerTrace)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.events WHERE trace_id = $1`, traceID); n != 1 {
		t.Fatalf("events.trace_id: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.outbox WHERE payload->>'traceId' = $1`, traceID); n != 1 {
		t.Fatalf("outbox traceId: %d", n)
	}

	// обработанных Событий ещё нет → beforeSha пуст
	if n := count(t, db, `SELECT count(*) FROM hub.outbox WHERE payload ? 'beforeSha'`); n != 0 {
		t.Fatalf("beforeSha on first manual: %d", n)
	}

	// повтор на том же коммите — идемпотентный no-op
	status, res = trigger(repoID, `{"commitSha":"headsha"}`)
	if status != http.StatusAccepted || !res.Duplicate {
		t.Fatalf("dup status=%d res=%+v", status, res)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.events`); n != 1 {
		t.Fatalf("events after dup: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.outbox`); n != 1 {
		t.Fatalf("outbox after dup: %d", n)
	}

	// репо без подписок никто не обслуживает: Событие в журнал (с beforeSha —
	// коммит последнего обработанного), Экземпляров/outbox не прибавляется
	if _, err := db.Exec(ctx, `DELETE FROM hub.build_subscriptions`); err != nil {
		t.Fatal(err)
	}
	// первое Событие обработано → следующий manual несёт beforeSha = его коммит
	if _, err := db.Exec(ctx, `UPDATE hub.instance_events SET processed_at = now()`); err != nil {
		t.Fatal(err)
	}
	status, res = trigger(repoID, `{"commitSha":"othersha"}`)
	if status != http.StatusAccepted || res.Duplicate || len(res.InstanceIDs) != 0 {
		t.Fatalf("no subscriptions status=%d res=%+v", status, res)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.events WHERE commit_sha = 'othersha' AND before_sha = 'headsha'`); n != 1 {
		t.Fatalf("events.before_sha: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.outbox`); n != 1 {
		t.Fatalf("outbox without subscriptions: %d", n)
	}
	// возвращаем подписку — дальше нужен обслуживающий Сборка
	if _, err := db.Exec(ctx, `INSERT INTO hub.build_subscriptions (build_id, repository_id) SELECT id, $1 FROM hub.agent_builds LIMIT 1`, repoID); err != nil {
		t.Fatal(err)
	}

	// mode=full: Событие full_scan, не дедупится об manual на том же коммите;
	// dedup-ключ — "full-"+eventId: полный скан НЕ привязан к коммиту
	status, res = trigger(repoID, `{"commitSha":"headsha","mode":"full"}`)
	if status != http.StatusAccepted || res.Duplicate || len(res.InstanceIDs) != 1 {
		t.Fatalf("full status=%d res=%+v", status, res)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.events WHERE action = 'full_scan' AND commit_sha = 'headsha'`); n != 1 {
		t.Fatalf("full_scan events: %d", n)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.instance_events WHERE dedup_key LIKE 'full-%'`); n != 1 {
		t.Fatalf("full dedup keys: %d", n)
	}
	// повторный full на том же коммите — НОВЫЙ прогон (каждый клик = отдельный аудит)
	if status, res = trigger(repoID, `{"commitSha":"headsha","mode":"full"}`); status != http.StatusAccepted || res.Duplicate {
		t.Fatalf("full rerun status=%d res=%+v", status, res)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.instance_events WHERE dedup_key LIKE 'full-%'`); n != 2 {
		t.Fatalf("full rerun dedup keys: %d", n)
	}

	// кривой mode — 400
	if status, _ := trigger(repoID, `{"mode":"turbo"}`); status != http.StatusBadRequest {
		t.Fatalf("bad mode status=%d", status)
	}

	// чужой/несуществующий репозиторий — 404
	if status, _ := trigger(999999, ""); status != http.StatusNotFound {
		t.Fatalf("unknown repo status=%d", status)
	}
}
