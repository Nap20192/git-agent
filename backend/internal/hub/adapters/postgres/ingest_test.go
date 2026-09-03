package postgres

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
)

// seedRepo — user+identity+connections+repo и N Сборок; возвращает repo и id Сборок.
func seedRepo(t *testing.T, db *pgxpool.Pool, builds int) (*domain.Repository, []int64) {
	t.Helper()
	ctx := context.Background()
	var userID, identityID, llmID, sbxID, repoID int64
	err := db.QueryRow(ctx, `
		WITH u AS (INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id),
		i AS (INSERT INTO hub.identities (user_id, provider, provider_user_id, username, access_token_enc)
		      SELECT id, 'github', 'gh-1', 't', '\x00' FROM u RETURNING id, user_id),
		l AS (INSERT INTO hub.llm_connections (user_id, name, api_base, api_key_enc, model)
		      SELECT id, 'llm', 'http://x', '\x00', 'm' FROM u RETURNING id),
		s AS (INSERT INTO hub.sandbox_connections (name, domain) VALUES ('sbx', 'x') RETURNING id)
		INSERT INTO hub.repositories (user_id, identity_id, provider, external_id, owner, name)
		SELECT i.user_id, i.id, 'github', '100', 'acme', 'repo' FROM i
		RETURNING user_id, identity_id, (SELECT id FROM l), (SELECT id FROM s), id`,
	).Scan(&userID, &identityID, &llmID, &sbxID, &repoID)
	if err != nil {
		t.Fatal(err)
	}
	ids := make([]int64, builds)
	for n := range builds {
		if err := db.QueryRow(ctx,
			`INSERT INTO hub.agent_builds (user_id, name, llm_connection_id, sandbox_connection_id)
			 VALUES ($1, $2, $3, $4) RETURNING id`,
			userID, fmt.Sprintf("b%d", n), llmID, sbxID).Scan(&ids[n]); err != nil {
			t.Fatal(err)
		}
	}
	return &domain.Repository{ID: repoID, UserID: userID, Provider: "github", Owner: "acme", Name: "repo"}, ids
}

// Веер (тикет 011): одно Событие + две Сборки → два Экземпляра, два журнала,
// две строки outbox с разными instanceId; дубль доставки — no-op целиком.
func TestIngestFanOut(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	store := &Store{Pool: db}
	repo, builds := seedRepo(t, db, 2)

	e := domain.Event{DeliveryID: "d-1", Action: "push", CommitSHA: "abc", Ref: "refs/heads/main"}
	dup, err := store.Ingest(ctx, repo, e, []byte(`{}`), builds)
	if err != nil {
		t.Fatal(err)
	}
	if dup {
		t.Fatal("first delivery marked duplicate")
	}

	var instances, journal int
	if err := db.QueryRow(ctx, `SELECT count(*), (SELECT count(*) FROM hub.instance_events)
		FROM hub.agent_instances`).Scan(&instances, &journal); err != nil {
		t.Fatal(err)
	}
	if instances != 2 || journal != 2 {
		t.Fatalf("instances=%d journal=%d, want 2/2", instances, journal)
	}

	rows, err := db.Query(ctx, `SELECT payload FROM hub.outbox ORDER BY id`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	seen := map[float64]bool{}
	for rows.Next() {
		var raw []byte
		if err := rows.Scan(&raw); err != nil {
			t.Fatal(err)
		}
		var msg map[string]any
		if err := json.Unmarshal(raw, &msg); err != nil {
			t.Fatal(err)
		}
		// контракт тикета 010: готовые id + dedupKey
		for _, k := range []string{"eventId", "instanceId", "threadId", "dedupKey"} {
			if msg[k] == nil {
				t.Errorf("message missing %s: %v", k, msg)
			}
		}
		seen[msg["instanceId"].(float64)] = true
	}
	if len(seen) != 2 {
		t.Fatalf("outbox messages with distinct instanceId: %d, want 2", len(seen))
	}

	// дубль доставки: ни Экземпляров, ни outbox сверх прежнего
	dup, err = store.Ingest(ctx, repo, e, []byte(`{}`), builds)
	if err != nil || !dup {
		t.Fatalf("dup=%v err=%v", dup, err)
	}
	var outbox int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM hub.outbox`).Scan(&outbox); err != nil {
		t.Fatal(err)
	}
	if outbox != 2 {
		t.Fatalf("outbox after dup: %d", outbox)
	}
}

// Ноль совпавших Сборок — Событие журналируется, outbox пуст.
func TestIngestNoBuilds(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	store := &Store{Pool: db}
	repo, _ := seedRepo(t, db, 0)

	e := domain.Event{DeliveryID: "d-1", Action: "issues"}
	if _, err := store.Ingest(ctx, repo, e, []byte(`{}`), nil); err != nil {
		t.Fatal(err)
	}
	var events, outbox int
	if err := db.QueryRow(ctx,
		`SELECT count(*), (SELECT count(*) FROM hub.outbox) FROM hub.events`).Scan(&events, &outbox); err != nil {
		t.Fatal(err)
	}
	if events != 1 || outbox != 0 {
		t.Fatalf("events=%d outbox=%d, want 1/0", events, outbox)
	}
}
