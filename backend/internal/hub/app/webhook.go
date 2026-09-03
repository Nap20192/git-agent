// Package app — прикладной слой hub: юзкейсы над доменными портами.
// Зависит только от domain (и pkg-утилит), не знает про HTTP/SQL/AMQP.
package app

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// WebhookService — приём События с вебхука (тикет 002): подлинность
// per-repo секретом, дедуп доставок, транзакционный ingest веером по
// подпискам Сборок (тикет 011).
// Любой отказ — молчаливый дроп с внутренним логом; наружу адаптер всегда отвечает 200.
type WebhookService struct {
	Repos    domain.RepositoryStore
	Subs     domain.SubscriptionStore
	Ingestor domain.EventIngestor
	Secrets  *secrets.Box
}

func (s *WebhookService) Handle(ctx context.Context, provider string, repoID int64, auth domain.WebhookAuth, e domain.Event, body []byte) {
	repo, err := s.Repos.Find(ctx, repoID, provider)
	if err != nil {
		slog.Error("webhook: repository lookup failed", "repositoryId", repoID, "err", err)
		return
	}
	if repo == nil {
		slog.Info("webhook: dropped, unknown repository", "repositoryId", repoID, "provider", provider)
		return
	}
	secret, err := s.Secrets.Decrypt(repo.WebhookSecretEnc)
	if err != nil {
		slog.Warn("webhook: dropped, no usable secret", "repositoryId", repoID)
		return
	}
	if !domain.VerifyWebhook(provider, string(secret), body, auth) {
		slog.Warn("webhook: dropped, invalid signature", "repositoryId", repoID, "provider", provider)
		return
	}

	duplicate, instanceIDs, err := s.FanOut(ctx, repo, e, body)
	if err != nil {
		slog.Error("webhook: ingest failed", "repositoryId", repoID, "deliveryId", e.DeliveryID, "err", err)
		return
	}
	if duplicate {
		slog.Info("webhook: duplicate delivery", "provider", provider, "deliveryId", e.DeliveryID)
	} else if len(instanceIDs) == 0 {
		slog.Info("webhook: no matching subscriptions, journaled only",
			"repositoryId", repoID, "action", e.Action, "ref", e.Ref)
	}
}

// FanOut — общий путь вебхука и ручного запуска (тикет 011): Сборки с
// совпавшей подпиской (репо вовсе без подписок обслуживает дефолтная Сборка
// на все события) → транзакционный ingest (журнал + Экземпляры + outbox).
func (s *WebhookService) FanOut(ctx context.Context, repo *domain.Repository, e domain.Event, payload []byte) (duplicate bool, instanceIDs []int64, err error) {
	subs, err := s.Subs.SubscriptionsByRepo(ctx, repo.ID)
	if err != nil {
		return false, nil, fmt.Errorf("subscriptions lookup: %w", err)
	}
	buildIDs := domain.MatchedBuilds(subs, e.Action, e.Ref)
	if len(subs) == 0 {
		def, err := s.Subs.DefaultBuild(ctx, repo.UserID)
		if err != nil {
			return false, nil, fmt.Errorf("default build lookup: %w", err)
		}
		if def != nil {
			buildIDs = []int64{def.ID}
		}
	}
	return s.Ingestor.Ingest(ctx, repo, e, payload, buildIDs)
}
