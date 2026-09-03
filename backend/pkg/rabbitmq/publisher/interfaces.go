package publisher

import "context"

type EventPublisher interface {
	// Publish шлёт persistent-сообщение и ждёт publisher confirm брокера.
	Publish(ctx context.Context, routingKey string, body []byte, contentType string) error
	Close() error
}
