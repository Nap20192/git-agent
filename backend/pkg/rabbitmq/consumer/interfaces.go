package consumer

import (
	"context"

	amqp "github.com/rabbitmq/amqp091-go"
)

type worker func(ctx context.Context, messages <-chan amqp.Delivery)

type EventConsumer interface {
	StartConsumer(ctx context.Context, fn worker) error
	// DeclareTopology создаёт exchange/queue/bind без запуска потребления —
	// для стороны-паблишера, чтобы очередь существовала до консьюмеров.
	DeclareTopology() error
}
