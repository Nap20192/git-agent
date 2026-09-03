// Package container — DI-контейнер hub: фабрика New собирает весь граф
// зависимостей (adapters → app → domain), Run запускает сервисы через
// errgroup с graceful shutdown, Close гасит ресурсы в обратном порядке.
package container

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"golang.org/x/sync/errgroup"

	"github.com/vnkjd/git-agent/backend/cmd/hub/config"
	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/httpapi"
	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/provider"
	rmq "github.com/vnkjd/git-agent/backend/internal/hub/adapters/rabbitmq"
	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/runnerapi"
	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/pkg/postgres"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

const shutdownTimeout = 5 * time.Second

type Container struct {
	Cfg *config.Config

	PG        postgres.DBEngine
	Store     *pgstore.Store
	Publisher *rmq.Publisher

	Webhook      *app.WebhookService
	Outbox       *app.OutboxService
	Repositories *app.RepositoryService
	Instances    *app.InstanceService
	Heartbeat    *app.HeartbeatService

	Server *http.Server
}

// New — фабрика: инстанцирует все зависимости в порядке слоёв.
func New(ctx context.Context, cfg *config.Config) (*Container, error) {
	box, err := secrets.New(cfg.SecretsKey)
	if err != nil {
		return nil, err
	}
	pg, err := postgres.NewPostgresDB(ctx, postgres.DBConnString(cfg.DatabaseURL))
	if err != nil {
		return nil, err
	}

	store := &pgstore.Store{Pool: pg.GetDB()}
	// TODO(auth, тикет 003): dev-пользователь до OAuth-входа
	devUserID, err := store.EnsureDevUser(ctx)
	if err != nil {
		pg.Close()
		return nil, err
	}

	publisher := &rmq.Publisher{URL: cfg.RabbitMQURL}
	providerClient := &provider.Client{}
	runnerClient := &runnerapi.Client{}

	webhook := &app.WebhookService{Repos: store, Ingestor: store, Secrets: box}
	outbox := &app.OutboxService{Store: store, Publisher: publisher}
	repositories := &app.RepositoryService{
		Repos: store, Identities: store, Provider: providerClient,
		Secrets: box, WebhookBaseURL: cfg.WebhookBaseURL,
	}
	instances := &app.InstanceService{
		Instances: store, Runners: store, Client: runnerClient,
		RunnersAlive: cfg.HeartbeatTimeout,
	}
	heartbeat := &app.HeartbeatService{Store: store, Timeout: cfg.HeartbeatTimeout}

	mux := httpapi.NewMux(httpapi.Handlers{
		Session:      &httpapi.Session{DevUserID: devUserID},
		Webhook:      &httpapi.WebhookHandler{Service: webhook},
		Runners:      &httpapi.RunnersHandler{Store: store, Token: cfg.RunnerToken},
		Identities:   &httpapi.IdentitiesHandler{Store: store, Provider: providerClient, Secrets: box},
		Repositories: &httpapi.RepositoriesHandler{Store: store, Service: repositories},
		Builds:       &httpapi.BuildsHandler{Store: store},
		Connections:  &httpapi.ConnectionsHandler{Store: store, Secrets: box},
		Instances:    &httpapi.InstancesHandler{Store: store, Service: instances},
	})

	return &Container{
		Cfg:          cfg,
		PG:           pg,
		Store:        store,
		Publisher:    publisher,
		Webhook:      webhook,
		Outbox:       outbox,
		Repositories: repositories,
		Instances:    instances,
		Heartbeat:    heartbeat,
		Server:       &http.Server{Addr: cfg.Addr, Handler: mux},
	}, nil
}

// Run запускает сервисы в errgroup и блокирует до отмены контекста либо
// падения любого из них; остальные гасятся отменой группового контекста.
func (c *Container) Run(ctx context.Context) error {
	g, ctx := errgroup.WithContext(ctx)

	g.Go(func() error {
		slog.Info("🌏 hub listening", "addr", c.Cfg.Addr)
		if err := c.Server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
			return err
		}
		return nil
	})
	g.Go(func() error {
		return c.Outbox.Run(ctx)
	})
	g.Go(func() error {
		return c.Heartbeat.Run(ctx)
	})
	g.Go(func() error {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
		defer cancel()
		return c.Server.Shutdown(shutdownCtx)
	})

	return g.Wait()
}

// Close освобождает ресурсы в порядке, обратном созданию.
func (c *Container) Close() {
	c.Publisher.Close()
	c.PG.Close()
}
