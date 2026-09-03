// Package rabbitmq — коннектор по образцу go-coffeeshop/pkg/rabbitmq:
// retry с бэкоффом до победы либо ошибки после _retryTimes попыток.
package rabbitmq

import (
	"errors"
	"time"

	"go.uber.org/zap"

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
			zap.S().Infow("📫 connected to rabbitmq 🎉")
			return connection, nil
		}
		counts++
		if counts > _retryTimes {
			zap.S().Errorw("failed to retry rabbitmq connection", "err", err)
			return nil, ErrCannotConnectRabbitMQ
		}
		zap.S().Infow("failed to connect to rabbitmq, backing off...", "seconds", _backOffSeconds, "err", err)
		time.Sleep(_backOffSeconds * time.Second)
	}
}
