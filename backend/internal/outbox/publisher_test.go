package outbox

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"

	"github.com/vnkjd/git-agent/backend/internal/testdb"
)

// Полный цикл: строка outbox → publish с confirm → published_at → сообщение в очереди.
func TestPublisher(t *testing.T) {
	url := os.Getenv("HUB_TEST_RABBITMQ_URL")
	if url == "" {
		url = "amqp://guest:guest@localhost:5673/"
	}
	probe, err := amqp.Dial(url)
	if err != nil {
		t.Skipf("rabbitmq unavailable: %v", err)
	}
	defer probe.Close()

	db := testdb.Setup(t)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	// минимальная цепочка FK до hub.events
	var eventID int64
	err = db.QueryRow(ctx, `
		WITH u AS (INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id),
		i AS (INSERT INTO hub.identities (user_id, provider, provider_user_id, username, access_token_enc)
		      SELECT id, 'github', 'gh-1', 't', '\x00' FROM u RETURNING id, user_id),
		r AS (INSERT INTO hub.repositories (user_id, identity_id, provider, external_id, owner, name)
		      SELECT i.user_id, i.id, 'github', '100', 'acme', 'repo' FROM i RETURNING id)
		INSERT INTO hub.events (provider, delivery_id, repository_id, action, payload)
		SELECT 'github', 'd-1', id, 'push', '{}' FROM r RETURNING id`).Scan(&eventID)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(ctx,
		`INSERT INTO hub.outbox (event_id, routing_key, payload) VALUES ($1, 'github.1.push', '{"eventId":1}')`,
		eventID); err != nil {
		t.Fatal(err)
	}

	go (&Publisher{DB: db, URL: url}).Run(ctx)

	deadline := time.Now().Add(10 * time.Second)
	for {
		var n int
		if err := db.QueryRow(ctx, `SELECT count(*) FROM hub.outbox WHERE published_at IS NOT NULL`).Scan(&n); err != nil {
			t.Fatal(err)
		}
		if n == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("outbox row never marked published")
		}
		time.Sleep(100 * time.Millisecond)
	}

	ch, err := probe.Channel()
	if err != nil {
		t.Fatal(err)
	}
	deadline = time.Now().Add(5 * time.Second)
	for {
		msg, ok, err := ch.Get(Queue, true)
		if err != nil {
			t.Fatal(err)
		}
		if ok {
			var body map[string]any
			if err := json.Unmarshal(msg.Body, &body); err != nil {
				t.Fatal(err)
			}
			// очередь durable и переживает прошлые прогоны — ищем своё сообщение
			if msg.RoutingKey == "github.1.push" && body["eventId"] == float64(1) {
				return
			}
			continue
		}
		if time.Now().After(deadline) {
			t.Fatal("message not found in queue")
		}
		time.Sleep(100 * time.Millisecond)
	}
}
