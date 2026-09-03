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
	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/oauth"
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

	publisher := &rmq.Publisher{URL: cfg.RabbitMQURL}
	providerClient := &provider.Client{}
	runnerClient := &runnerapi.Client{FirstByteTimeout: cfg.ChatFirstByteTimeout}
	oauthClient := &oauth.Client{
		GitHub: oauth.App{ClientID: cfg.GitHubOAuthID, ClientSecret: cfg.GitHubOAuthSecret},
		GitLab: oauth.App{ClientID: cfg.GitLabOAuthID, ClientSecret: cfg.GitLabOAuthSecret},
	}

	auth := &app.AuthService{Store: store, OAuth: oauthClient, Secrets: box}
	webhook := &app.WebhookService{Repos: store, Subs: store, Ingestor: store, Secrets: box}
	outbox := &app.OutboxService{Store: store, Publisher: publisher}
	repositories := &app.RepositoryService{
		Repos: store, Identities: store, Subs: store, Provider: providerClient,
		Auth: auth, Webhook: webhook, Secrets: box, WebhookBaseURL: cfg.WebhookBaseURL,
	}
	instances := &app.InstanceService{
		Instances: store, Runners: store, Client: runnerClient,
		RunnersAlive: cfg.HeartbeatTimeout,
	}
	heartbeat := &app.HeartbeatService{Store: store, Timeout: cfg.HeartbeatTimeout}

	session := &httpapi.Session{Store: store, DevUserID: cfg.DevUserID}
	if cfg.DevUserID != 0 {
		slog.Warn("hub: DEV_USER_ID auth bypass is active — dev only", "userId", cfg.DevUserID)
	}
	mux := httpapi.NewMux(httpapi.Handlers{
		Session: session,
		Auth: &httpapi.AuthHandler{
			Service: auth, Session: session, Store: store,
			Identities: store, FrontendURL: cfg.FrontendURL, PublicBaseURL: cfg.OAuthRedirectBase,
		},
		Webhook:       &httpapi.WebhookHandler{Service: webhook},
		Runners:       &httpapi.RunnersHandler{Store: store, Token: cfg.RunnerToken},
		Identities:    &httpapi.IdentitiesHandler{Store: store, Provider: providerClient, Auth: auth},
		Repositories:  &httpapi.RepositoriesHandler{Store: store, Subs: store, Service: repositories},
		Subscriptions: &httpapi.SubscriptionsHandler{Store: store, Repos: store},
		Builds:        &httpapi.BuildsHandler{Store: store},
		Connections:   &httpapi.ConnectionsHandler{Store: store, Secrets: box},
		Instances:     &httpapi.InstancesHandler{Store: store, Service: instances},
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
