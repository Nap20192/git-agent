// Package outbox — воркер transactional outbox (тикет 005): поллинг батчами
// по порядку id, публикация через pkg/rabbitmq/publisher (confirm-режим),
// published_at только после confirm — at-least-once.
package outbox

import (
	"context"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/vnkjd/git-agent/backend/pkg/rabbitmq"
	"github.com/vnkjd/git-agent/backend/pkg/rabbitmq/consumer"
	"github.com/vnkjd/git-agent/backend/pkg/rabbitmq/publisher"
)

const (
	batchSize    = 100
	pollInterval = time.Second
)

type Worker struct {
	DB  *pgxpool.Pool
	URL string
}

// Run поллит outbox и публикует до отмены контекста. Обрыв Rabbit — новая
// сессия с бэкоффом; outbox и есть буфер, вебхуки от этого не страдают.
func (w *Worker) Run(ctx context.Context) {
	for ctx.Err() == nil {
		if err := w.session(ctx); err != nil && ctx.Err() == nil {
			slog.Warn("outbox: rabbit session ended, reconnecting", "err", err)
			select {
			case <-time.After(3 * time.Second):
			case <-ctx.Done():
			}
		}
	}
}

func (w *Worker) session(ctx context.Context) error {
	conn, err := rabbitmq.NewRabbitMQConn(rabbitmq.RabbitMQConnStr(w.URL))
	if err != nil {
		return err
	}
	defer conn.Close()

	// durable-очередь с биндом # декларируется до первой публикации,
	// чтобы События не терялись, пока раннеров-консьюмеров ещё нет
	if err := consumer.NewConsumer(conn).DeclareTopology(); err != nil {
		return err
	}
	pub, err := publisher.NewPublisher(conn)
	if err != nil {
		return err
	}
	defer pub.Close()

	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			if err := w.drain(ctx, pub); err != nil {
				return err
			}
		}
	}
}

// drain — батч неопубликованных по порядку id; confirm каждого перед published_at.
// ponytail: один воркер, без SKIP LOCKED — добавить при горизонтальном масштабировании hub.
func (w *Worker) drain(ctx context.Context, pub publisher.EventPublisher) error {
	for {
		rows, err := w.DB.Query(ctx,
			`SELECT id, routing_key, payload FROM hub.outbox
			  WHERE published_at IS NULL ORDER BY id LIMIT $1`, batchSize)
		if err != nil {
			slog.Error("outbox: poll failed", "err", err)
			return nil // БД отпадёт и вернётся; rabbit-сессию не рвём
		}
		type msg struct {
			id      int64
			key     string
			payload []byte
		}
		var batch []msg
		for rows.Next() {
			var m msg
			if err := rows.Scan(&m.id, &m.key, &m.payload); err != nil {
				rows.Close()
				return err
			}
			batch = append(batch, m)
		}
		rows.Close()
		if len(batch) == 0 {
			return nil
		}
		for _, m := range batch {
			if err := pub.Publish(ctx, m.key, m.payload, "application/json"); err != nil {
				return err
			}
			if _, err := w.DB.Exec(ctx,
				`UPDATE hub.outbox SET published_at = now() WHERE id = $1`, m.id); err != nil {
				slog.Error("outbox: mark published failed (duplicate delivery possible)", "outboxId", m.id, "err", err)
				return nil
			}
		}
		if len(batch) < batchSize {
			return nil
		}
	}
}
