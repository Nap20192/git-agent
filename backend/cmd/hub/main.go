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
	// Один формат на процесс: текст с уровнем из LOG_LEVEL (JSON — когда появится сборщик логов).
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: cfg.LogLevel})))

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	c, err := container.New(ctx, cfg)
	if err != nil {
		return err
	}
	defer c.Close()

	return c.Run(ctx)
}
