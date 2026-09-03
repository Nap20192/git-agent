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
	Provider       domain.ProviderClient
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
	token, err := s.Secrets.Decrypt(ident.AccessTokenEnc)
	if err != nil {
		return nil, err
	}
	pr, err := s.Provider.Repo(ctx, ident.Provider, string(token), externalID)
	if err != nil {
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
		BuildID:          buildID,
	}
	// id репозитория нужен в URL хука — сначала строка, потом хук у провайдера
	repo.ID, err = s.Repos.CreateRepository(ctx, repo)
	if err != nil {
		return nil, err
	}
	hookURL := fmt.Sprintf("%s/hooks/%s/%d", s.WebhookBaseURL, ident.Provider, repo.ID)
	hookID, err := s.Provider.CreateHook(ctx, ident.Provider, string(token), *pr, hookURL, hookSecret)
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
			if token, err := s.Secrets.Decrypt(ident.AccessTokenEnc); err == nil {
				if err := s.Provider.DeleteHook(ctx, repo.Provider, string(token), repo, *repo.WebhookProviderID); err != nil {
					slog.Warn("repository: provider hook removal failed, disconnecting anyway",
						"repositoryId", id, "err", err)
				}
			}
		}
	}
	return s.Repos.DeleteRepository(ctx, id)
}
