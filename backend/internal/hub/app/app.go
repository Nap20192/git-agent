// Package app — сборка hub по образцу go-coffeeshop/internal/<svc>/app:
// App держит зависимости, New их собирает, Run поднимает воркеры и HTTP.
package app

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/cmd/hub/config"
	"github.com/vnkjd/git-agent/backend/internal/hub/outbox"
	"github.com/vnkjd/git-agent/backend/internal/hub/runners"
	"github.com/vnkjd/git-agent/backend/internal/hub/webhook"
	"github.com/vnkjd/git-agent/backend/pkg/postgres"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

type App struct {
	Cfg *config.Config
	PG  postgres.DBEngine
}

func New(ctx context.Context, cfg *config.Config) (*App, error) {
	pg, err := postgres.NewPostgresDB(ctx, postgres.DBConnString(cfg.DatabaseURL))
	if err != nil {
		return nil, err
	}
	return &App{Cfg: cfg, PG: pg}, nil
}

// Run блокирует до отмены контекста: outbox-воркер + HTTP-сервер, graceful shutdown.
func (a *App) Run(ctx context.Context) error {
	defer a.PG.Close()

	box, err := secrets.New(a.Cfg.SecretsKey)
	if err != nil {
		return err
	}
	db := a.PG.GetDB()

	go (&outbox.Worker{DB: db, URL: a.Cfg.RabbitMQURL}).Run(ctx)

	rn := &runners.Handler{DB: db, Token: a.Cfg.RunnerToken}
	mux := http.NewServeMux()
	mux.Handle("POST /hooks/{provider}/{repositoryId}", &webhook.Handler{DB: db, Secrets: box})
	mux.HandleFunc("POST /api/runners", rn.Auth(rn.Register))
	mux.HandleFunc("POST /api/runners/{id}/heartbeat", rn.Auth(rn.Heartbeat))
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	srv := &http.Server{Addr: a.Cfg.Addr, Handler: mux}
	errc := make(chan error, 1)
	go func() { errc <- srv.ListenAndServe() }()
	slog.Info("🌏 hub listening", "addr", a.Cfg.Addr)

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
