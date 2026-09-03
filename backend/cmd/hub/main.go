// hub — Go-бекенд git-agent: вебхуки, outbox→RabbitMQ, реестр раннеров.
// Спека: .wayfinder/map.md; схема БД: migrations/backend/001_init.sql.
package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/vnkjd/git-agent/backend/cmd/hub/config"
	"github.com/vnkjd/git-agent/backend/internal/hub/app"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		slog.Error("failed get config", "err", err)
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	a, err := app.New(ctx, cfg)
	if err != nil {
		slog.Error("failed init app", "err", err)
		os.Exit(1)
	}
	if err := a.Run(ctx); err != nil {
		slog.Error("hub: fatal", "err", err)
		os.Exit(1)
	}
}
