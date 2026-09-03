// hub — Go-бекенд git-agent: вебхуки, outbox→RabbitMQ, реестр раннеров.
// Граф зависимостей собирает internal/hub/container (фабрика New),
// сервисы бегут в errgroup с graceful shutdown. Спека: .wayfinder/map.md.
package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/vnkjd/git-agent/backend/cmd/hub/config"
	"github.com/vnkjd/git-agent/backend/internal/hub/container"
	"github.com/vnkjd/git-agent/backend/pkg/logger"
)

func main() {
	if err := run(); err != nil {
		slog.Error("hub: fatal", "err", err)
		os.Exit(1)
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	logger.Setup(cfg.LogLevel, cfg.LogFormat)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	c, err := container.New(ctx, cfg)
	if err != nil {
		return err
	}
	defer c.Close()

	return c.Run(ctx)
}
