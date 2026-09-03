package domain

import "context"

// RepositoryStore — чтение подключённых Репозиториев.
type RepositoryStore interface {
	// Find возвращает nil, nil если Репозиторий не подключён.
	Find(ctx context.Context, id int64, provider string) (*Repository, error)
}

// EventIngestor — приём События в одной транзакции: журнал events
// (дедуп по provider+delivery_id) + upsert Экземпляра Агента + строка outbox.
type EventIngestor interface {
	// Ingest возвращает duplicate=true для повторной доставки (no-op).
	Ingest(ctx context.Context, repo *Repository, e Event, payload []byte) (duplicate bool, err error)
}

// OutboxMessage — неопубликованная строка hub.outbox.
type OutboxMessage struct {
	ID         int64
	RoutingKey string
	Payload    []byte
}

// OutboxStore — очередь transactional outbox.
type OutboxStore interface {
	Unpublished(ctx context.Context, limit int) ([]OutboxMessage, error)
	MarkPublished(ctx context.Context, id int64) error
}

// EventPublisher — публикация События в брокер; возврат без ошибки означает,
// что брокер подтвердил приём (publisher confirm) — контракт outbox, тикет 005.
type EventPublisher interface {
	Publish(ctx context.Context, routingKey string, payload []byte) error
}

// Runner — регистрация Раннера (тикет 004).
type Runner struct {
	ID      int64
	Name    string
	Address string
	Slots   int
}

// RunnerStore — реестр Раннеров.
type RunnerStore interface {
	// Upsert по уникальному имени; повторная регистрация обновляет адрес/слоты.
	Upsert(ctx context.Context, r Runner) (int64, error)
	// Heartbeat возвращает false для неизвестного Раннера.
	Heartbeat(ctx context.Context, id int64) (bool, error)
}
