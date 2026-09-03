// Package rabbitmq — outbound-адаптер брокера: domain.EventPublisher поверх
// pkg/rabbitmq. Соединение ленивое, обрыв — переподключение на следующем
// Publish; Publish возвращается только после publisher confirm.
package rabbitmq

import (
	"context"
	"sync"

	amqp "github.com/rabbitmq/amqp091-go"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/rabbitmq"
	"github.com/vnkjd/git-agent/backend/pkg/rabbitmq/consumer"
	"github.com/vnkjd/git-agent/backend/pkg/rabbitmq/publisher"
)

type Publisher struct {
	URL string

	mu   sync.Mutex
	conn *amqp.Connection
	pub  publisher.EventPublisher
}

var _ domain.EventPublisher = (*Publisher)(nil)

func (p *Publisher) Publish(ctx context.Context, routingKey string, payload []byte) error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if err := p.ensure(); err != nil {
		return err
	}
	if err := p.pub.Publish(ctx, routingKey, payload, "application/json"); err != nil {
		p.reset()
		return err
	}
	return nil
}

func (p *Publisher) ensure() error {
	if p.pub != nil && !p.conn.IsClosed() {
		return nil
	}
	p.reset()

	conn, err := rabbitmq.NewRabbitMQConn(rabbitmq.RabbitMQConnStr(p.URL))
	if err != nil {
		return err
	}
	// durable-очередь с биндом # декларируется до первой публикации,
	// чтобы События не терялись, пока раннеров-консьюмеров ещё нет
	if err := consumer.NewConsumer(conn).DeclareTopology(); err != nil {
		conn.Close()
		return err
	}
	pub, err := publisher.NewPublisher(conn)
	if err != nil {
		conn.Close()
		return err
	}
	p.conn, p.pub = conn, pub
	return nil
}

func (p *Publisher) reset() {
	if p.conn != nil {
		p.conn.Close() // закрывает и каналы
	}
	p.conn, p.pub = nil, nil
}

func (p *Publisher) Close() {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.reset()
}
