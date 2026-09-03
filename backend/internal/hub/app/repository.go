package app

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log/slog"

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
	Auth           *AuthService // токены связок + refresh-флоу
	Secrets        *secrets.Box
	WebhookBaseURL string
}

func (s *RepositoryService) Connect(ctx context.Context, userID, identityID int64, externalID string, buildID *int64) (*domain.Repository, error) {
	ident, err := s.Identities.Identity(ctx, identityID, userID)
	if err != nil {
		return nil, err
	}
	if ident == nil {
		return nil, fmt.Errorf("identity %d: %w", identityID, domain.ErrNotFound)
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
				slog.Error("repository: rollback after subscription failure", "repositoryId", repo.ID, "err", delErr)
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
			slog.Error("repository: rollback after hook failure", "repositoryId", repo.ID, "err", delErr)
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
				slog.Warn("repository: provider hook removal failed, disconnecting anyway",
					"repositoryId", id, "err", err)
			}
		}
	}
	return s.Repos.DeleteRepository(ctx, id)
}
