// Package outbox — паблишер transactional outbox в RabbitMQ (тикет 005).
// Topic exchange `events`, одна durable-очередь с биндом `#`, persistent-сообщения;
// published_at ставится только после publisher confirm — at-least-once.
package outbox

import (
	"context"
	"log/slog"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	Exchange     = "events"
	Queue        = "events.all"
	batchSize    = 100
	pollInterval = time.Second
)

type Publisher struct {
	DB  *pgxpool.Pool
	URL string
}

// Run поллит outbox и публикует до отмены контекста. Обрыв Rabbit — reconnect
// с бэкоффом; outbox и есть буфер, вебхуки от этого не страдают.
func (p *Publisher) Run(ctx context.Context) {
	for ctx.Err() == nil {
		if err := p.session(ctx); err != nil && ctx.Err() == nil {
			slog.Warn("outbox: rabbit session ended, reconnecting", "err", err)
			select {
			case <-time.After(3 * time.Second):
			case <-ctx.Done():
			}
		}
	}
}

func (p *Publisher) session(ctx context.Context) error {
	conn, err := amqp.Dial(p.URL)
	if err != nil {
		return err
	}
	defer conn.Close()
	ch, err := conn.Channel()
	if err != nil {
		return err
	}
	if err := ch.Confirm(false); err != nil {
		return err
	}
	if err := ch.ExchangeDeclare(Exchange, "topic", true, false, false, false, nil); err != nil {
		return err
	}
	if _, err := ch.QueueDeclare(Queue, true, false, false, false, nil); err != nil {
		return err
	}
	if err := ch.QueueBind(Queue, "#", Exchange, false, nil); err != nil {
		return err
	}
	slog.Info("outbox: connected to rabbit", "exchange", Exchange, "queue", Queue)

	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			if err := p.drain(ctx, ch); err != nil {
				return err
			}
		}
	}
}

// drain — батч неопубликованных по порядку id; ждём confirm каждого сообщения.
// ponytail: один паблишер, без SKIP LOCKED — добавить при горизонтальном масштабировании hub.
func (p *Publisher) drain(ctx context.Context, ch *amqp.Channel) error {
	for {
		rows, err := p.DB.Query(ctx,
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
			conf, err := ch.PublishWithDeferredConfirmWithContext(ctx, Exchange, m.key, false, false,
				amqp.Publishing{
					ContentType:  "application/json",
					DeliveryMode: amqp.Persistent,
					Body:         m.payload,
				})
			if err != nil {
				return err
			}
			ok, err := conf.WaitContext(ctx)
			if err != nil {
				return err
			}
			if !ok {
				slog.Warn("outbox: nack from broker, will retry", "outboxId", m.id)
				return nil
			}
			if _, err := p.DB.Exec(ctx,
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
