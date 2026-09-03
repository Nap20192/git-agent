// Package rabbitmq — коннектор по образцу go-coffeeshop/pkg/rabbitmq:
// retry с бэкоффом до победы либо ошибки после _retryTimes попыток.
package rabbitmq

import (
	"errors"
	"log/slog"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

const (
	_retryTimes     = 5
	_backOffSeconds = 2
)

type RabbitMQConnStr string

var ErrCannotConnectRabbitMQ = errors.New("cannot connect to rabbit")

func NewRabbitMQConn(rabbitMqURL RabbitMQConnStr) (*amqp.Connection, error) {
	var counts int64
	for {
		connection, err := amqp.Dial(string(rabbitMqURL))
		if err == nil {
			slog.Info("rabbitmq: connected")
			return connection, nil
		}
		counts++
		if counts > _retryTimes {
			slog.Error("rabbitmq: connect failed, giving up", "err", err)
			return nil, ErrCannotConnectRabbitMQ
		}
		slog.Warn("rabbitmq: connect failed, backing off", "seconds", _backOffSeconds, "err", err)
		time.Sleep(_backOffSeconds * time.Second)
	}
}
