// Package consumer — по образцу go-coffeeshop/pkg/rabbitmq/consumer:
// декларация exchange/queue/bind + Qos + пул воркеров над одним каналом.
// Отличия: topic-exchange по умолчанию (топология тикета 005), контекст
// снаружи, завершение по ctx.Done() или закрытию канала.
package consumer

import (
	"context"
	"fmt"
	"log/slog"

	amqp "github.com/rabbitmq/amqp091-go"
)

const (
	_exchangeDurable    = true
	_exchangeAutoDelete = false
	_exchangeInternal   = false
	_exchangeNoWait     = false

	_queueDurable    = true
	_queueAutoDelete = false
	_queueExclusive  = false
	_queueNoWait     = false

	_prefetchCount  = 5
	_prefetchSize   = 0
	_prefetchGlobal = false

	_consumeAutoAck   = false
	_consumeExclusive = false
	_consumeNoLocal   = false
	_consumeNoWait    = false

	_exchangeName   = "events"
	_exchangeKind   = "topic"
	_queueName      = "events.all"
	_bindingKey     = "#"
	_consumerTag    = "events-consumer"
	_workerPoolSize = 8
)

type consumer struct {
	exchangeName, exchangeKind, queueName, bindingKey, consumerTag string
	workerPoolSize                                                 int
	amqpConn                                                       *amqp.Connection
}

var _ EventConsumer = (*consumer)(nil)

func NewConsumer(amqpConn *amqp.Connection, opts ...Option) EventConsumer {
	sub := &consumer{
		amqpConn:       amqpConn,
		exchangeName:   _exchangeName,
		exchangeKind:   _exchangeKind,
		queueName:      _queueName,
		bindingKey:     _bindingKey,
		consumerTag:    _consumerTag,
		workerPoolSize: _workerPoolSize,
	}
	for _, opt := range opts {
		opt(sub)
	}
	return sub
}

func (c *consumer) DeclareTopology() error {
	ch, err := c.createChannel()
	if err != nil {
		return err
	}
	return ch.Close()
}

// StartConsumer блокирует до ctx.Done() либо закрытия канала брокером.
func (c *consumer) StartConsumer(ctx context.Context, fn worker) error {
	ch, err := c.createChannel()
	if err != nil {
		return err
	}
	defer ch.Close()

	deliveries, err := ch.Consume(
		c.queueName,
		c.consumerTag,
		_consumeAutoAck,
		_consumeExclusive,
		_consumeNoLocal,
		_consumeNoWait,
		nil,
	)
	if err != nil {
		return fmt.Errorf("ch.Consume: %w", err)
	}

	for range c.workerPoolSize {
		go fn(ctx, deliveries)
	}

	select {
	case <-ctx.Done():
		return ctx.Err()
	case chanErr := <-ch.NotifyClose(make(chan *amqp.Error)):
		return chanErr
	}
}

func (c *consumer) createChannel() (*amqp.Channel, error) {
	ch, err := c.amqpConn.Channel()
	if err != nil {
		return nil, fmt.Errorf("amqpConn.Channel: %w", err)
	}

	if err := ch.ExchangeDeclare(
		c.exchangeName,
		c.exchangeKind,
		_exchangeDurable,
		_exchangeAutoDelete,
		_exchangeInternal,
		_exchangeNoWait,
		nil,
	); err != nil {
		return nil, fmt.Errorf("ch.ExchangeDeclare: %w", err)
	}

	queue, err := ch.QueueDeclare(
		c.queueName,
		_queueDurable,
		_queueAutoDelete,
		_queueExclusive,
		_queueNoWait,
		nil,
	)
	if err != nil {
		return nil, fmt.Errorf("ch.QueueDeclare: %w", err)
	}

	if err := ch.QueueBind(
		queue.Name,
		c.bindingKey,
		c.exchangeName,
		_queueNoWait,
		nil,
	); err != nil {
		return nil, fmt.Errorf("ch.QueueBind: %w", err)
	}

	if err := ch.Qos(_prefetchCount, _prefetchSize, _prefetchGlobal); err != nil {
		return nil, fmt.Errorf("ch.Qos: %w", err)
	}

	slog.Info("consumer bound to exchange",
		"queue", queue.Name, "exchange", c.exchangeName, "binding_key", c.bindingKey, "consumer_tag", c.consumerTag)
	return ch, nil
}
