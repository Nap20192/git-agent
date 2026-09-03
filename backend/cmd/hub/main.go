// hub — Go-бекенд git-agent: вебхуки, outbox→RabbitMQ, реестр раннеров.
// Граф зависимостей собирает internal/hub/container (фабрика New),
// сервисы бегут в errgroup с graceful shutdown. Спека: .wayfinder/map.md.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"go.uber.org/zap"

	"github.com/vnkjd/git-agent/backend/cmd/hub/config"
	"github.com/vnkjd/git-agent/backend/internal/hub/container"
)

func main() {
	logger := newLogger()
	defer logger.Sync() //nolint:errcheck // stderr
	zap.ReplaceGlobals(logger)
	if err := run(); err != nil {
		zap.S().Errorw("hub: fatal", "err", err)
		os.Exit(1)
	}
}

// newLogger — HUB_ENV=prod → JSON-продакшен, иначе dev-консоль (цвет, caller, stacktrace на warn).
func newLogger() *zap.Logger {
	if os.Getenv("HUB_ENV") == "prod" {
		return zap.Must(zap.NewProduction())
	}
	return zap.Must(zap.NewDevelopment())
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	c, err := container.New(ctx, cfg)
	if err != nil {
		return err
	}
	defer c.Close()

	return c.Run(ctx)
}
