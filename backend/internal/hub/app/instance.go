package app

import (
	"bytes"
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

// Terminal — команда стрим-консоли в песочнице Экземпляра (SSE-поток раннера,
// кадры TerminalEvent). В отличие от Chat, down-Экземпляр НЕ поднимается и
// песочница НЕ создаётся (её создаёт пользователь в UI) — 409.
func (s *InstanceService) Terminal(ctx context.Context, id, userID int64, command string) (io.ReadCloser, error) {
	inst, err := s.Instances.Instance(ctx, id, userID)
	if err != nil {
		return nil, err
	}
	if inst == nil {
		return nil, domain.ErrNotFound
	}
	if inst.Status != "running" || inst.RunnerID == nil {
		return nil, fmt.Errorf("instance is down — raise the agent first: %w", domain.ErrConflict)
	}
	runner, err := s.Runners.Runner(ctx, *inst.RunnerID)
	if err != nil {
		return nil, err
	}
	if runner == nil {
		return nil, fmt.Errorf("runner of instance is gone: %w", domain.ErrConflict)
	}
	return s.Client.Terminal(ctx, runner.Address, inst.ID, command)
}

// Activity — activity-кадры хода для графа Рана (тикет 012). Running-Экземпляр
// — SSE-прокси в его Раннер (живой ход стримится, прошлый раннер реплеит сам);
// down-Экземпляр либо пропавший Раннер — hub отдаёт реплей из hub.activity
// без раннера. eventID nil = живой либо последний ход.
func (s *InstanceService) Activity(ctx context.Context, id, userID int64, eventID *int64) (io.ReadCloser, error) {
	inst, err := s.Instances.Instance(ctx, id, userID)
	if err != nil {
		return nil, err
	}
	if inst == nil {
		return nil, domain.ErrNotFound
	}
	if inst.Status == "running" && inst.RunnerID != nil {
		if runner, err := s.Runners.Runner(ctx, *inst.RunnerID); err == nil && runner != nil {
			stream, err := s.Client.Activity(ctx, runner.Address, inst.ID, eventID)
			if err == nil {
				return stream, nil
			}
			slog.Warn("instance: runner activity failed, replaying from db", "instanceId", inst.ID, "err", err)
		}
	}
	frames, err := s.Instances.Activity(ctx, inst.ID, eventID)
	if err != nil {
		return nil, err
	}
	return replayStream(frames), nil
}

// replayStream — готовое SSE-тело из сохранённых кадров + терминальный done.
func replayStream(frames [][]byte) io.ReadCloser {
	var b bytes.Buffer
	for _, f := range frames {
		b.WriteString("data: ")
		b.Write(f)
		b.WriteString("\n\n")
	}
	b.WriteString("data: {\"kind\": \"done\"}\n\n")
	return io.NopCloser(&b)
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
	// занятый раннер сам ставит raise/chat в очередь — слоты не фильтруем
	runner, err := s.Runners.AliveRunner(ctx, s.RunnersAlive)
	if err != nil {
		return nil, err
	}
	if runner == nil {
		return nil, fmt.Errorf("no alive runner: %w", domain.ErrConflict)
	}
	if err := s.Client.Raise(ctx, runner.Address, inst.ID); err != nil {
		return nil, fmt.Errorf("raise instance on runner %s: %w", runner.Name, err)
	}
	if err := s.Instances.SetInstanceRunning(ctx, inst.ID, runner.ID); err != nil {
		return nil, err
	}
	return runner, nil
}
