// Package app — прикладной слой hub: юзкейсы над доменными портами.
// Зависит только от domain (и pkg-утилит), не знает про HTTP/SQL/AMQP.
package app

import (
	"context"
	"fmt"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
	"github.com/vnkjd/git-agent/backend/pkg/trace"
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
	log := trace.Logger(ctx)
	repo, err := s.Repos.Find(ctx, repoID, provider)
	if err != nil {
		log.Errorw("webhook: repository lookup failed", "repositoryId", repoID, "err", err)
		return
	}
	if repo == nil {
		log.Infow("webhook: dropped, unknown repository", "repositoryId", repoID, "provider", provider)
		return
	}
	secret, err := s.Secrets.Decrypt(repo.WebhookSecretEnc)
	if err != nil {
		log.Warnw("webhook: dropped, no usable secret", "repositoryId", repoID)
		return
	}
	if !domain.VerifyWebhook(provider, string(secret), body, auth) {
		log.Warnw("webhook: dropped, invalid signature", "repositoryId", repoID, "provider", provider)
		return
	}

	duplicate, instanceIDs, err := s.FanOut(ctx, repo, e, body)
	if err != nil {
		log.Errorw("webhook: ingest failed", "repositoryId", repoID, "deliveryId", e.DeliveryID, "err", err)
		return
	}
	if duplicate {
		log.Infow("webhook: duplicate delivery", "provider", provider, "deliveryId", e.DeliveryID)
	} else if len(instanceIDs) == 0 {
		log.Infow("webhook: no matching subscriptions, journaled only",
			"repositoryId", repoID, "action", e.Action, "ref", e.Ref)
	}
}

// FanOut — общий путь вебхука и ручного запуска (тикет 011): Сборки с
// совпавшей подпиской (репо вовсе без подписок обслуживает дефолтная Сборка
// на все события) → транзакционный ingest (журнал + Экземпляры + outbox).
// trace_id События = trace_id запроса (вебхука или /trigger) из ctx.
func (s *WebhookService) FanOut(ctx context.Context, repo *domain.Repository, e domain.Event, payload []byte) (duplicate bool, instanceIDs []int64, err error) {
	if e.TraceID = trace.FromContext(ctx); e.TraceID == "" {
		e.TraceID = trace.New()
	}
	buildIDs, err := s.MatchedBuilds(ctx, repo, e.Action, e.Ref)
	if err != nil {
		return false, nil, err
	}
	// Событие без кода (ping, issues, comments) — только в журнал: Экземпляр под
	// него не поднимаем, раннер такой ход всё равно пропускает (skipped_no_commit).
	// Иначе ping сразу после подключения плодит Экземпляр дефолтной Сборки,
	// который потом висит рядом с настоящими подписками.
	if e.CommitSHA == "" && e.HeadSHA == "" && e.Action != "full_scan" {
		buildIDs = nil
	}
	return s.Ingestor.Ingest(ctx, repo, e, payload, buildIDs)
}

// MatchedBuilds — Сборки, которые получат Событие (action, ref) Репозитория:
// по подпискам, а у репо без подписок — дефолтная Сборка юзера.
func (s *WebhookService) MatchedBuilds(ctx context.Context, repo *domain.Repository, action, ref string) ([]int64, error) {
	subs, err := s.Subs.SubscriptionsByRepo(ctx, repo.ID)
	if err != nil {
		return nil, fmt.Errorf("subscriptions lookup: %w", err)
	}
	buildIDs := domain.MatchedBuilds(subs, action, ref)
	if len(subs) == 0 {
		def, err := s.Subs.DefaultBuild(ctx, repo.UserID)
		if err != nil {
			return nil, fmt.Errorf("default build lookup: %w", err)
		}
		if def != nil {
			buildIDs = []int64{def.ID}
		}
	}
	return buildIDs, nil
}
