package app

import (
	"context"
	"fmt"

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
	Builds      domain.BuildStore // sandbox_connection Сборки для авто-провижининга
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

// Ensure — авто-провижининг (тикет 004, решение изменено): у Экземпляра нет
// живой песочницы (не привязана либо dead) — hub создаёт её из
// sandbox_connection Сборки этого Экземпляра тем же путём, что ручной
// POST /api/sandbox-instances, и привязывает. Зовётся перед публикацией
// События (/trigger) и перед raise (chat/raise). Ошибка — наверх без
// публикации: OpenSandbox → 502 upstream, подключение без image → 400.
func (s *SandboxService) Ensure(ctx context.Context, inst *domain.AgentInstance, userID int64) error {
	if inst.SandboxInstanceID != nil && inst.SandboxStatus != nil && *inst.SandboxStatus == "alive" {
		return nil
	}
	build, err := s.Builds.Build(ctx, inst.BuildID)
	if err != nil {
		return err
	}
	if build == nil {
		return fmt.Errorf("build %d of instance %d is gone: %w", inst.BuildID, inst.ID, domain.ErrNotFound)
	}
	si, err := s.Create(ctx, build.SandboxConnectionID)
	if err != nil {
		return fmt.Errorf("provision sandbox for instance %d: %w", inst.ID, err)
	}
	if err := s.Store.LinkInstanceSandbox(ctx, inst.ID, si.ID, userID); err != nil {
		return err
	}
	inst.SandboxInstanceID, inst.SandboxExternalID, inst.SandboxStatus = &si.ID, &si.ExternalID, &si.Status
	return nil
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
