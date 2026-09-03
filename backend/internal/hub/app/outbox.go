package app

import (
	"context"
	"log/slog"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

const (
	outboxBatchSize    = 100
	outboxPollInterval = time.Second
)

// OutboxService — воркер transactional outbox (тикет 005): поллинг батчами
// по порядку id, MarkPublished только после подтверждённой публикации —
// at-least-once, дубли гасит дедуп Экземпляра.
type OutboxService struct {
	Store     domain.OutboxStore
	Publisher domain.EventPublisher
}

// Run поллит outbox до отмены контекста (тогда возвращает nil — штатное
// завершение). Ошибки публикации/БД не фатальны: строка остаётся
// неопубликованной и уйдёт на следующем тике.
func (s *OutboxService) Run(ctx context.Context) error {
	ticker := time.NewTicker(outboxPollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			s.drain(ctx)
		}
	}
}

// ponytail: один воркер, без SKIP LOCKED — добавить при горизонтальном масштабировании hub.
func (s *OutboxService) drain(ctx context.Context) {
	for {
		batch, err := s.Store.Unpublished(ctx, outboxBatchSize)
		if err != nil {
			slog.ErrorContext(ctx, "outbox: poll failed", "err", err)
			return
		}
		if len(batch) == 0 {
			return
		}
		for _, m := range batch {
			if err := s.Publisher.Publish(ctx, m.RoutingKey, m.Payload); err != nil {
				slog.WarnContext(ctx, "outbox: publish failed, will retry", "outboxId", m.ID, "err", err)
				return
			}
			if err := s.Store.MarkPublished(ctx, m.ID); err != nil {
				slog.ErrorContext(ctx, "outbox: mark published failed (duplicate delivery possible)", "outboxId", m.ID, "err", err)
				return
			}
		}
		if len(batch) < outboxBatchSize {
			return
		}
	}
}
