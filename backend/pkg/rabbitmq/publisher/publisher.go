// Package publisher — по образцу go-coffeeshop/pkg/rabbitmq/publisher.
// Отличия от оригинала: один канал в confirm-режиме на весь публишер
// (Publish возвращается только после confirm брокера — контракт outbox,
// тикет 005), routing key — аргумент Publish, а не фиксированная опция.
package publisher

import (
	"context"
	"fmt"

	amqp "github.com/rabbitmq/amqp091-go"
)

const (
	_publishMandatory = false
	_publishImmediate = false

	_exchangeName = "events"
	_exchangeKind = "topic"
)

type publisher struct {
	exchangeName, exchangeKind string
	messageTypeName            string
	amqpChan                   *amqp.Channel
}

var _ EventPublisher = (*publisher)(nil)

// NewPublisher открывает канал, включает confirm-режим и декларирует durable exchange.
func NewPublisher(amqpConn *amqp.Connection, opts ...Option) (EventPublisher, error) {
	pub := &publisher{
		exchangeName: _exchangeName,
		exchangeKind: _exchangeKind,
	}
	for _, opt := range opts {
		opt(pub)
	}

	ch, err := amqpConn.Channel()
	if err != nil {
		return nil, fmt.Errorf("amqpConn.Channel: %w", err)
	}
	if err := ch.Confirm(false); err != nil {
		ch.Close()
		return nil, fmt.Errorf("ch.Confirm: %w", err)
	}
	if err := ch.ExchangeDeclare(pub.exchangeName, pub.exchangeKind, true, false, false, false, nil); err != nil {
		ch.Close()
		return nil, fmt.Errorf("ch.ExchangeDeclare: %w", err)
	}
	pub.amqpChan = ch
	return pub, nil
}

func (p *publisher) Publish(ctx context.Context, routingKey string, body []byte, contentType string) error {
	conf, err := p.amqpChan.PublishWithDeferredConfirmWithContext(
		ctx,
		p.exchangeName,
		routingKey,
		_publishMandatory,
		_publishImmediate,
		amqp.Publishing{
			ContentType:  contentType,
			DeliveryMode: amqp.Persistent,
			Body:         body,
			Type:         p.messageTypeName,
		},
	)
	if err != nil {
		return fmt.Errorf("ch.Publish: %w", err)
	}
	ok, err := conf.WaitContext(ctx)
	if err != nil {
		return fmt.Errorf("confirm wait: %w", err)
	}
	if !ok {
		return fmt.Errorf("broker nack for routing key %s", routingKey)
	}
	return nil
}

func (p *publisher) Close() error {
	return p.amqpChan.Close()
}
