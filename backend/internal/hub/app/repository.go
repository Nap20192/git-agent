package app

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"go.uber.org/zap"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// RepositoryService — подключение/отключение Репозиториев (тикет 002):
// хук вешает сам backend через API провайдера, per-repo секрет — в БД шифром.
type RepositoryService struct {
	Repos          domain.RepositoryAdmin
	Identities     domain.IdentityStore
	Subs           domain.SubscriptionStore
	Provider       domain.ProviderClient
	Auth           *AuthService    // токены связок + refresh-флоу
	Webhook        *WebhookService // общий fan-out для ручного запуска
	Secrets        *secrets.Box
	WebhookBaseURL string
}

func (s *RepositoryService) Connect(ctx context.Context, userID, identityID int64, externalID string, buildID *int64) (*domain.Repository, error) {
	ident, err := s.Identities.Identity(ctx, identityID, userID)
	if err != nil {
		return nil, err
	}
	if ident == nil {
		return nil, fmt.Errorf("identity %d is not connected: %w", identityID, domain.ErrNotFound)
	}
	var pr *domain.ProviderRepo
	if err := s.Auth.CallWithToken(ctx, ident, func(token string) error {
		var err error
		pr, err = s.Provider.Repo(ctx, ident.Provider, token, externalID)
		return err
	}); err != nil {
		return nil, err
	}

	secret := make([]byte, 32)
	if _, err := rand.Read(secret); err != nil {
		return nil, err
	}
	hookSecret := hex.EncodeToString(secret)
	secretEnc, err := s.Secrets.Encrypt([]byte(hookSecret))
	if err != nil {
		return nil, err
	}

	repo := &domain.Repository{
		UserID:           userID,
		IdentityID:       identityID,
		Provider:         ident.Provider,
		ExternalID:       pr.ExternalID,
		Owner:            pr.Owner,
		Name:             pr.Name,
		DefaultBranch:    pr.DefaultBranch,
		WebhookSecretEnc: secretEnc,
	}
	// id репозитория нужен в URL хука — сначала строка, потом хук у провайдера
	repo.ID, err = s.Repos.CreateRepository(ctx, repo)
	if err != nil {
		return nil, err
	}
	// buildId в запросе (deprecated) = подписка этой Сборки на все события
	if buildID != nil {
		if _, err := s.Subs.UpsertSubscription(ctx, &domain.BuildSubscription{
			BuildID: *buildID, RepositoryID: repo.ID,
		}); err != nil {
			if delErr := s.Repos.DeleteRepository(ctx, repo.ID); delErr != nil {
				zap.S().Errorw("repository: rollback after subscription failure", "repositoryId", repo.ID, "err", delErr)
			}
			return nil, err
		}
		repo.BuildID = buildID
	}
	hookURL := fmt.Sprintf("%s/hooks/%s/%d", s.WebhookBaseURL, ident.Provider, repo.ID)
	var hookID string
	err = s.Auth.CallWithToken(ctx, ident, func(token string) error {
		var err error
		hookID, err = s.Provider.CreateHook(ctx, ident.Provider, token, *pr, hookURL, hookSecret)
		return err
	})
	if err != nil {
		if delErr := s.Repos.DeleteRepository(ctx, repo.ID); delErr != nil {
			zap.S().Errorw("repository: rollback after hook failure", "repositoryId", repo.ID, "err", delErr)
		}
		return nil, fmt.Errorf("create provider hook: %w", err)
	}
	if err := s.Repos.SetWebhook(ctx, repo.ID, hookID); err != nil {
		return nil, err
	}
	repo.WebhookProviderID = &hookID
	return repo, nil
}

// Disconnect снимает хук у провайдера (best effort: хук мог уже исчезнуть —
// подключение всё равно удаляем) и удаляет Репозиторий (События каскадом).
func (s *RepositoryService) Disconnect(ctx context.Context, id, userID int64) error {
	repo, err := s.Repos.Repository(ctx, id, userID)
	if err != nil {
		return err
	}
	if repo == nil {
		return domain.ErrNotFound
	}
	if repo.WebhookProviderID != nil {
		if ident, err := s.Identities.Identity(ctx, repo.IdentityID, userID); err == nil && ident != nil {
			err := s.Auth.CallWithToken(ctx, ident, func(token string) error {
				return s.Provider.DeleteHook(ctx, repo.Provider, token, repo, *repo.WebhookProviderID)
			})
			if err != nil {
				zap.S().Warnw("repository: provider hook removal failed, disconnecting anyway",
					"repositoryId", id, "err", err)
			}
		}
	}
	return s.Repos.DeleteRepository(ctx, id)
}

// TriggerResult — итог ручного запуска: на каком коммите и какие Экземпляры.
// Duplicate — этот коммит уже запускали вручную (идемпотентный no-op, как
// повторная доставка push).
type TriggerResult struct {
	CommitSHA   string
	Duplicate   bool
	InstanceIDs []int64
}

// Trigger — ручной запуск агента (без вебхука): резолвит HEAD ветки через
// API провайдера (если commitSHA не задан), синтезирует Событие action=manual
// (mode=full — action=full_scan, полный аудит) и прогоняет его тем же fan-out,
// что и вебхук. delivery_id детерминирован по (режим, репо, коммит) —
// повторный запуск на том же коммите дедупится журналом.
func (s *RepositoryService) Trigger(ctx context.Context, userID, id int64, ref, commitSHA, mode string) (*TriggerResult, error) {
	repo, err := s.Repos.Repository(ctx, id, userID)
	if err != nil {
		return nil, err
	}
	if repo == nil {
		return nil, domain.ErrNotFound
	}
	if ref == "" && repo.DefaultBranch != nil {
		ref = *repo.DefaultBranch
	}
	if commitSHA == "" {
		if ref == "" {
			return nil, fmt.Errorf("trigger: ref is required (default branch unknown): %w", domain.ErrConflict)
		}
		ident, err := s.Identities.Identity(ctx, repo.IdentityID, userID)
		if err != nil {
			return nil, err
		}
		if ident == nil {
			return nil, fmt.Errorf("identity %d of the repository is gone: %w", repo.IdentityID, domain.ErrNotFound)
		}
		if err := s.Auth.CallWithToken(ctx, ident, func(token string) error {
			var err error
			commitSHA, err = s.Provider.BranchHead(ctx, repo.Provider, token, repo, ref)
			return err
		}); err != nil {
			return nil, fmt.Errorf("resolve %q head: %w", ref, err)
		}
	}

	// manual идемпотентен по коммиту (детерминированный delivery_id);
	// full НЕ привязан к коммиту — каждый запуск отдельный прогон.
	action := "manual"
	deliveryID := fmt.Sprintf("manual-%d-%s", repo.ID, commitSHA)
	if mode == "full" {
		action = "full_scan"
		deliveryID = fmt.Sprintf("full-%d-%s-%d", repo.ID, commitSHA, time.Now().UnixNano())
	}
	e := domain.Event{
		DeliveryID: deliveryID,
		Action:     action,
		CommitSHA:  commitSHA,
		Ref:        ref,
	}
	payload, _ := json.Marshal(map[string]any{
		"action": action, "ref": ref, "commitSha": commitSHA, "userId": userID,
	})
	duplicate, instanceIDs, err := s.Webhook.FanOut(ctx, repo, e, payload)
	if err != nil {
		return nil, err
	}
	return &TriggerResult{CommitSHA: commitSHA, Duplicate: duplicate, InstanceIDs: instanceIDs}, nil
}

// ProviderRepos — репозитории провайдера токеном связки (401 от провайдера —
// refresh-флоу внутри CallWithToken). Ошибка провайдера — ErrUpstream: наружу
// 502 без деталей, детали — в лог на границе.
func (s *RepositoryService) ProviderRepos(ctx context.Context, userID, identityID int64) ([]domain.ProviderRepo, error) {
	ident, err := s.Identities.Identity(ctx, identityID, userID)
	if err != nil {
		return nil, err
	}
	if ident == nil {
		return nil, domain.ErrNotFound
	}
	var repos []domain.ProviderRepo
	err = s.Auth.CallWithToken(ctx, ident, func(token string) error {
		var err error
		repos, err = s.Provider.Repos(ctx, ident.Provider, token)
		return err
	})
	if errors.Is(err, domain.ErrUnauthorized) {
		return nil, fmt.Errorf("%s rejected the access token — reconnect the account: %w", ident.Provider, domain.ErrUpstream)
	}
	if err != nil {
		return nil, fmt.Errorf("%s repos: %w: %w", ident.Provider, err, domain.ErrUpstream)
	}
	return repos, nil
}

// SetBuild — deprecated (тикет 011): {buildId} транслируется в подписку
// Сборки на все события Репозитория; возвращает обновлённый Репозиторий.
func (s *RepositoryService) SetBuild(ctx context.Context, id, userID, buildID int64) (*domain.Repository, error) {
	repo, err := s.Repos.Repository(ctx, id, userID)
	if err != nil {
		return nil, err
	}
	if repo == nil {
		return nil, domain.ErrNotFound
	}
	if _, err := s.Subs.UpsertSubscription(ctx, &domain.BuildSubscription{BuildID: buildID, RepositoryID: id}); err != nil {
		return nil, err
	}
	repo, err = s.Repos.Repository(ctx, id, userID)
	if err != nil {
		return nil, err
	}
	if repo == nil {
		return nil, domain.ErrNotFound
	}
	return repo, nil
}
