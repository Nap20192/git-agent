package app

import (
	"context"
	"testing"
	"time"

	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
)

// Протухший Раннер: его running-Экземпляр → down, необработанное Событие —
// снова в outbox; обработанное — нет. Повторный тик — no-op (не зациклится).
func TestRequeueStale(t *testing.T) {
	db := testdb.Setup(t)
	ctx := context.Background()
	userID, instID := seedInstance(t, db)
	_ = userID

	// раннер с протухшим heartbeat владеет running-Экземпляром
	var runnerID int64
	if err := db.QueryRow(ctx,
		`INSERT INTO hub.runners (name, address, slots, last_heartbeat_at)
		 VALUES ('dead', 'http://dead', 2, now() - interval '10 minutes') RETURNING id`).Scan(&runnerID); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(ctx,
		`UPDATE hub.agent_instances SET status = 'running', runner_id = $2 WHERE id = $1`, instID, runnerID); err != nil {
		t.Fatal(err)
	}

	// два События: одно обработано, одно нет; оба уже публиковались (published_at стоит)
	seedEvent := func(delivery, dedup string, processed bool) {
		var eventID int64
		if err := db.QueryRow(ctx,
			`INSERT INTO hub.events (provider, delivery_id, repository_id, action, payload)
			 SELECT 'github', $1, repository_id, 'push', '{}' FROM hub.agent_instances WHERE id = $2
			 RETURNING id`, delivery, instID).Scan(&eventID); err != nil {
			t.Fatal(err)
		}
		if _, err := db.Exec(ctx,
			`INSERT INTO hub.outbox (event_id, routing_key, payload, published_at)
			 VALUES ($1, 'github.1.push',
			         jsonb_build_object('eventId', $1::bigint, 'instanceId', $2::bigint), now())`,
			eventID, instID); err != nil {
			t.Fatal(err)
		}
		var processedAt any
		if processed {
			processedAt = time.Now()
		}
		if _, err := db.Exec(ctx,
			`INSERT INTO hub.instance_events (instance_id, event_id, dedup_key, processed_at)
			 VALUES ($1, $2, $3, $4)`, instID, eventID, dedup, processedAt); err != nil {
			t.Fatal(err)
		}
	}
	seedEvent("d-1", "sha-unprocessed", false)
	seedEvent("d-2", "sha-processed", true)

	store := &pgstore.Store{Pool: db}
	downed, requeued, err := store.RequeueStale(ctx, 30*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if downed != 1 || requeued != 1 {
		t.Fatalf("downed=%d requeued=%d, want 1/1", downed, requeued)
	}

	var status string
	if err := db.QueryRow(ctx,
		`SELECT status FROM hub.agent_instances WHERE id = $1`, instID).Scan(&status); err != nil {
		t.Fatal(err)
	}
	if status != "down" {
		t.Errorf("instance status: %s", status)
	}
	var unpublished int
	if err := db.QueryRow(ctx,
		`SELECT count(*) FROM hub.outbox WHERE published_at IS NULL`).Scan(&unpublished); err != nil {
		t.Fatal(err)
	}
	if unpublished != 1 {
		t.Errorf("unpublished outbox rows: %d, want 1 (только необработанное Событие)", unpublished)
	}

	// повторный тик: Экземпляры уже down — ничего не дублируется
	downed, requeued, err = store.RequeueStale(ctx, 30*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if downed != 0 || requeued != 0 {
		t.Fatalf("second tick: downed=%d requeued=%d, want 0/0", downed, requeued)
	}
}
