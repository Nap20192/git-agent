// hub — Go-бекенд git-agent: вебхуки, outbox→RabbitMQ, реестр раннеров.
// Композиционный корень: собирает adapters → app → domain (гексагональная
// архитектура, зависимости направлены внутрь). Спека: .wayfinder/map.md.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/vnkjd/git-agent/backend/cmd/hub/config"
	httpapi "github.com/vnkjd/git-agent/backend/internal/hub/adapters/httpapi"
	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	rmq "github.com/vnkjd/git-agent/backend/internal/hub/adapters/rabbitmq"
	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/pkg/postgres"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
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
	box, err := secrets.New(cfg.SecretsKey)
	if err != nil {
		return err
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	pg, err := postgres.NewPostgresDB(ctx, postgres.DBConnString(cfg.DatabaseURL))
	if err != nil {
		return err
	}
	defer pg.Close()

	store := &pgstore.Store{Pool: pg.GetDB()}
	pub := &rmq.Publisher{URL: cfg.RabbitMQURL}
	defer pub.Close()

	go (&app.OutboxService{Store: store, Publisher: pub}).Run(ctx)

	mux := httpapi.NewMux(
		&httpapi.WebhookHandler{Service: &app.WebhookService{Repos: store, Ingestor: store, Secrets: box}},
		&httpapi.RunnersHandler{Store: store, Token: cfg.RunnerToken},
	)
	srv := &http.Server{Addr: cfg.Addr, Handler: mux}
	errc := make(chan error, 1)
	go func() { errc <- srv.ListenAndServe() }()
	slog.Info("🌏 hub listening", "addr", cfg.Addr)

	select {
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		return srv.Shutdown(shutdownCtx)
	case err := <-errc:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	}
}
