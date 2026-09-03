// hub — Go-бекенд git-agent: вебхуки, outbox→RabbitMQ, реестр раннеров.
// Спека: .wayfinder/map.md; схема БД: migrations/backend/001_init.sql.
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

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/vnkjd/git-agent/backend/internal/config"
	"github.com/vnkjd/git-agent/backend/internal/outbox"
	"github.com/vnkjd/git-agent/backend/internal/runners"
	"github.com/vnkjd/git-agent/backend/internal/secrets"
	"github.com/vnkjd/git-agent/backend/internal/webhook"
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

	db, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer db.Close()
	if err := db.Ping(ctx); err != nil {
		return err
	}

	go (&outbox.Publisher{DB: db, URL: cfg.RabbitMQURL}).Run(ctx)

	rn := &runners.Handler{DB: db, Token: cfg.RunnerToken}
	mux := http.NewServeMux()
	mux.Handle("POST /hooks/{provider}/{repositoryId}", &webhook.Handler{DB: db, Secrets: box})
	mux.HandleFunc("POST /api/runners", rn.Auth(rn.Register))
	mux.HandleFunc("POST /api/runners/{id}/heartbeat", rn.Auth(rn.Heartbeat))
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	srv := &http.Server{Addr: cfg.Addr, Handler: mux}
	errc := make(chan error, 1)
	go func() { errc <- srv.ListenAndServe() }()
	slog.Info("hub: listening", "addr", cfg.Addr)

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
