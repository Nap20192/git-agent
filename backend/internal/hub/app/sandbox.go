package app

import (
	"context"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// SandboxService — жизненный цикл Экземпляров Сэндбоксов: создаёт/убивает их
// hub по команде юзера через lifecycle-API подключения (раннер только
// подключается по external_id). Скоуп — как у sandbox-подключений:
// глобальный (в схеме нет user_id).
type SandboxService struct {
	Store       domain.SandboxInstanceStore
	Connections domain.ConnectionStore
	Client      domain.SandboxLifecycle
	Secrets     *secrets.Box
	Defaults    domain.Defaults // image старых подключений без image → SANDBOX_IMAGE
}

// Create — OpenSandbox create (no-TTL) по координатам подключения + строка
// hub.sandbox_instances; подключение без image — ValidationError.
func (s *SandboxService) Create(ctx context.Context, connectionID int64) (*domain.SandboxInstance, error) {
	conn, err := s.Connections.SandboxConnection(ctx, connectionID)
	if err != nil {
		return nil, err
	}
	if conn == nil {
		return nil, domain.ErrNotFound
	}
	conn.ApplyDefaults(s.Defaults)
	if conn.Image == nil || *conn.Image == "" {
		return nil, domain.Invalid("sandbox connection has no image configured (set SANDBOX_IMAGE in .env)")
	}
	apiKey, err := s.apiKey(conn)
	if err != nil {
		return nil, err
	}
	externalID, err := s.Client.CreateSandbox(ctx, conn.Domain, apiKey, *conn.Image)
	if err != nil {
		return nil, err
	}
	id, err := s.Store.CreateSandboxInstance(ctx, externalID, conn.ID)
	if err != nil {
		return nil, err
	}
	si, err := s.Store.SandboxInstance(ctx, id)
	if err != nil {
		return nil, err
	}
	if si == nil {
		return nil, domain.ErrNotFound
	}
	return si, nil
}

// Kill — destroy у OpenSandbox + status=dead. Идемпотентно: уже dead — no-op
// без похода в OpenSandbox.
func (s *SandboxService) Kill(ctx context.Context, id int64) error {
	si, err := s.Store.SandboxInstance(ctx, id)
	if err != nil {
		return err
	}
	if si == nil {
		return domain.ErrNotFound
	}
	if si.Status == "dead" {
		return nil
	}
	conn, err := s.Connections.SandboxConnection(ctx, si.SandboxConnectionID)
	if err != nil {
		return err
	}
	var addr, apiKey string
	if conn != nil {
		addr = conn.Domain
		apiKey, _ = s.apiKey(conn) // нерасшифровываемый ключ — пробуем без него
	}
	if err := s.Client.DeleteSandbox(ctx, addr, apiKey, si.ExternalID); err != nil {
		return err
	}
	return s.Store.MarkSandboxInstanceDead(ctx, id)
}

func (s *SandboxService) apiKey(conn *domain.SandboxConnection) (string, error) {
	if conn.APIKeyEnc == nil {
		return "", nil
	}
	key, err := s.Secrets.Decrypt(conn.APIKeyEnc)
	return string(key), err
}
