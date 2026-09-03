package app

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// InstanceService — операции над Экземплярами через Раннеров (тикет 004):
// чат проксируется в раннер; down-Экземпляр сначала поднимается на Раннере
// со свободным слотом.
type InstanceService struct {
	Instances    domain.InstanceStore
	Runners      domain.RunnerStore
	Client       domain.RunnerClient
	RunnersAlive time.Duration // окно живости heartbeat при выборе Раннера
}

// Chat поднимает down-Экземпляр (raise на свободном Раннере) и возвращает
// SSE-поток раннера (кадры ChatEvent, hub проксирует как есть).
func (s *InstanceService) Chat(ctx context.Context, id, userID int64, message string) (io.ReadCloser, error) {
	inst, err := s.Instances.Instance(ctx, id, userID)
	if err != nil {
		return nil, err
	}
	if inst == nil {
		return nil, domain.ErrNotFound
	}
	runner, err := s.ensureRunning(ctx, inst)
	if err != nil {
		return nil, err
	}
	return s.Client.Chat(ctx, runner.Address, inst.ID, message)
}

// Stop опускает running-Экземпляр через его Раннер; down — no-op.
func (s *InstanceService) Stop(ctx context.Context, id, userID int64) error {
	inst, err := s.Instances.Instance(ctx, id, userID)
	if err != nil {
		return err
	}
	if inst == nil {
		return domain.ErrNotFound
	}
	if inst.Status != "running" {
		return nil
	}
	if inst.RunnerID != nil {
		if runner, err := s.Runners.Runner(ctx, *inst.RunnerID); err == nil && runner != nil {
			if err := s.Client.Stop(ctx, runner.Address, inst.ID); err != nil {
				slog.Warn("instance: runner stop failed, marking down anyway", "instanceId", inst.ID, "err", err)
			}
		}
	}
	return s.Instances.SetInstanceDown(ctx, inst.ID)
}

// ensureRunning — running-Экземпляр возвращает его Раннер; down — выбирает
// свободный живой Раннер, просит raise и фиксирует single-running в БД.
// ponytail: два конкурентных чата могут поднять дважды — гонка закрывается
// advisory-lock по id Экземпляра, когда станет реальной проблемой.
func (s *InstanceService) ensureRunning(ctx context.Context, inst *domain.AgentInstance) (*domain.Runner, error) {
	if inst.Status == "running" && inst.RunnerID != nil {
		runner, err := s.Runners.Runner(ctx, *inst.RunnerID)
		if err != nil {
			return nil, err
		}
		if runner != nil {
			return runner, nil
		}
	}
	runner, err := s.Runners.FreeRunner(ctx, s.RunnersAlive)
	if err != nil {
		return nil, err
	}
	if runner == nil {
		return nil, fmt.Errorf("no alive runner with a free slot: %w", domain.ErrConflict)
	}
	if err := s.Client.Raise(ctx, runner.Address, inst.ID); err != nil {
		return nil, fmt.Errorf("raise instance on runner %s: %w", runner.Name, err)
	}
	if err := s.Instances.SetInstanceRunning(ctx, inst.ID, runner.ID); err != nil {
		return nil, err
	}
	return runner, nil
}
