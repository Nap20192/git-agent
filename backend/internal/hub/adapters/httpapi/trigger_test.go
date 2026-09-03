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

	// фейковый GitHub: HEAD default-ветки
	gh := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
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
	session := &Session{Store: store, DevUserID: userID}
	mux := http.NewServeMux()
	h := &RepositoriesHandler{Store: store, Subs: store, Service: svc}
	mux.HandleFunc("POST /api/repositories/{id}/trigger", session.Wrap(h.Trigger))
	srv := httptest.NewServer(mux)
	defer srv.Close()

	trigger := func(repoID int64, body string) (int, triggerResultDTO) {
		t.Helper()
		resp, err := http.Post(srv.URL+"/api/repositories/"+strconv.FormatInt(repoID, 10)+"/trigger",
			"application/json", bytes.NewBufferString(body))
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

	// репо без подписок → дефолтная Сборка (как в webhook)
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
	status, res = trigger(repoID, `{"commitSha":"othersha"}`)
	if status != http.StatusAccepted || res.Duplicate || len(res.InstanceIDs) != 1 {
		t.Fatalf("fallback status=%d res=%+v", status, res)
	}
	if n := count(t, db, `SELECT count(*) FROM hub.agent_instances WHERE build_id = $1`, defaultBuild); n != 1 {
		t.Fatalf("instances for default build: %d", n)
	}

	// чужой/несуществующий репозиторий — 404
	if status, _ := trigger(999999, ""); status != http.StatusNotFound {
		t.Fatalf("unknown repo status=%d", status)
	}
}
