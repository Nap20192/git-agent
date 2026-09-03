// Package postgres — outbound-адаптер хранения: реализация доменных портов
// hub поверх pgx-пула (схема hub.*, migrations/backend/001_init.sql).
package postgres

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

type Store struct {
	Pool *pgxpool.Pool
}

var (
	_ domain.RepositoryStore = (*Store)(nil)
	_ domain.EventIngestor   = (*Store)(nil)
	_ domain.OutboxStore     = (*Store)(nil)
	_ domain.RunnerStore     = (*Store)(nil)
)

func (s *Store) Find(ctx context.Context, id int64, provider string) (*domain.Repository, error) {
	r := domain.Repository{ID: id, Provider: provider}
	err := s.Pool.QueryRow(ctx,
		`SELECT user_id, owner, name, webhook_secret_enc
		   FROM hub.repositories WHERE id = $1 AND provider = $2`,
		id, provider,
	).Scan(&r.UserID, &r.Owner, &r.Name, &r.WebhookSecretEnc)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &r, nil
}

// Ingest — одна транзакция: журнал hub.events (дедуп по provider+delivery_id)
// + веер (тикет 011): upsert Экземпляра каждой Сборки из buildIDs, журнал
// instance_events, строка outbox на каждый Экземпляр (контракт тикета 010 —
// в сообщении готовые instanceId/threadId). Ноль Сборок — только журнал.
func (s *Store) Ingest(ctx context.Context, repo *domain.Repository, e domain.Event, payload []byte, buildIDs []int64) (bool, error) {
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)

	var eventID int64
	err = tx.QueryRow(ctx,
		`INSERT INTO hub.events (provider, delivery_id, repository_id, action, commit_sha, ref, payload)
		 VALUES ($1, $2, $3, $4, NULLIF($5, ''), NULLIF($6, ''), $7)
		 ON CONFLICT (provider, delivery_id) DO NOTHING
		 RETURNING id`,
		repo.Provider, e.DeliveryID, repo.ID, e.Action, e.CommitSHA, e.Ref, payload,
	).Scan(&eventID)
	if errors.Is(err, pgx.ErrNoRows) {
		return true, nil
	}
	if err != nil {
		return false, fmt.Errorf("insert event: %w", err)
	}

	routingKey := domain.RoutingKey(repo.Provider, repo.ID, e.Action)
	for _, buildID := range buildIDs {
		var instanceID int64
		var threadID string
		err = tx.QueryRow(ctx,
			`INSERT INTO hub.agent_instances (build_id, repository_id, thread_id)
			 VALUES ($1, $2, $3)
			 ON CONFLICT (build_id, repository_id) DO UPDATE SET updated_at = now()
			 RETURNING id, thread_id`,
			buildID, repo.ID, fmt.Sprintf("hub-%d-%d", buildID, repo.ID),
		).Scan(&instanceID, &threadID)
		if err != nil {
			return false, fmt.Errorf("upsert instance (build %d): %w", buildID, err)
		}
		if _, err := tx.Exec(ctx,
			`INSERT INTO hub.instance_events (instance_id, event_id, dedup_key)
			 VALUES ($1, $2, $3) ON CONFLICT DO NOTHING`,
			instanceID, eventID, domain.DedupKey(eventID, e),
		); err != nil {
			return false, fmt.Errorf("insert instance event: %w", err)
		}
		if _, err := tx.Exec(ctx,
			`INSERT INTO hub.outbox (event_id, routing_key, payload) VALUES ($1, $2, $3)`,
			eventID, routingKey, domain.EventMessage(eventID, instanceID, threadID, repo, e),
		); err != nil {
			return false, fmt.Errorf("insert outbox: %w", err)
		}
	}
	return false, tx.Commit(ctx)
}

func (s *Store) Unpublished(ctx context.Context, limit int) ([]domain.OutboxMessage, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT id, routing_key, payload FROM hub.outbox
		  WHERE published_at IS NULL ORDER BY id LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var batch []domain.OutboxMessage
	for rows.Next() {
		var m domain.OutboxMessage
		if err := rows.Scan(&m.ID, &m.RoutingKey, &m.Payload); err != nil {
			return nil, err
		}
		batch = append(batch, m)
	}
	return batch, rows.Err()
}

func (s *Store) MarkPublished(ctx context.Context, id int64) error {
	_, err := s.Pool.Exec(ctx, `UPDATE hub.outbox SET published_at = now() WHERE id = $1`, id)
	return err
}

func (s *Store) Upsert(ctx context.Context, r domain.Runner) (int64, error) {
	var id int64
	err := s.Pool.QueryRow(ctx,
		`INSERT INTO hub.runners (name, address, slots)
		 VALUES ($1, $2, $3)
		 ON CONFLICT (name) DO UPDATE
		   SET address = $2, slots = $3, last_heartbeat_at = now()
		 RETURNING id`,
		r.Name, r.Address, r.Slots,
	).Scan(&id)
	return id, err
}

func (s *Store) Heartbeat(ctx context.Context, id int64) (bool, error) {
	tag, err := s.Pool.Exec(ctx,
		`UPDATE hub.runners SET last_heartbeat_at = now() WHERE id = $1`, id)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() > 0, nil
}
