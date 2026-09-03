package app

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/trace"
)

// InstanceService — операции над Экземплярами через Раннеров (тикет 004):
// чат проксируется в раннер; down-Экземпляр сначала поднимается на Раннере
// со свободным слотом.
type InstanceService struct {
	Instances    domain.InstanceStore
	Runners      domain.RunnerStore
	Client       domain.RunnerClient
	Sandboxes    *SandboxService // авто-провижининг песочницы перед raise; nil — выключен
	RunnersAlive time.Duration   // окно живости heartbeat при выборе Раннера
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
	runner, _, err := s.ensureRunning(ctx, inst, userID)
	if err != nil {
		return nil, err
	}
	// queued игнорируем: чат сам встаёт в очередь на раннере (first-byte таймаут)
	return s.Client.Chat(ctx, runner.Address, inst.ID, message)
}

// Raise — явный подъём Экземпляра: queued=true — раннер поставил подъём в
// очередь за слотом (202 наружу), фронт показывает «в очереди за слотом».
func (s *InstanceService) Raise(ctx context.Context, id, userID int64) (bool, error) {
	inst, err := s.Instances.Instance(ctx, id, userID)
	if err != nil {
		return false, err
	}
	if inst == nil {
		return false, domain.ErrNotFound
	}
	_, queued, err := s.ensureRunning(ctx, inst, userID)
	return queued, err
}

// Resume — «Продолжить»: незавершённые События Экземпляра — снова в outbox
// (механика heartbeat-ре-публикации); раннер поднимет Экземпляр сам, получив
// Событие из очереди. Возвращает пере-опубликованные eventId (пусто = нечего).
func (s *InstanceService) Resume(ctx context.Context, id, userID int64) ([]int64, error) {
	inst, err := s.Instances.Instance(ctx, id, userID)
	if err != nil {
		return nil, err
	}
	if inst == nil {
		return nil, domain.ErrNotFound
	}
	return s.Instances.RequeueInstance(ctx, inst.ID)
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
			trace.Logger(ctx).Warnw("instance: runner activity failed, replaying from db", "instanceId", inst.ID, "err", err)
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
				trace.Logger(ctx).Warnw("instance: runner stop failed, marking down anyway", "instanceId", inst.ID, "err", err)
			}
		}
	}
	return s.Instances.SetInstanceDown(ctx, inst.ID)
}

// ensureRunning — running-Экземпляр возвращает его Раннер; down — сначала
// живая песочница (нет/dead — hub создаёт сам, тикет 004), затем живой
// Раннер и raise. Раннер отвечает быстро: running — фиксируем
// single-running в БД; queued — слот занят, раннер поднимет фоном и сам
// зафиксирует running (клейм CAS), статус в БД не трогаем.
// ponytail: два конкурентных чата могут поднять дважды — гонка закрывается
// advisory-lock по id Экземпляра, когда станет реальной проблемой.
func (s *InstanceService) ensureRunning(ctx context.Context, inst *domain.AgentInstance, userID int64) (*domain.Runner, bool, error) {
	if inst.Status == "running" && inst.RunnerID != nil {
		runner, err := s.Runners.Runner(ctx, *inst.RunnerID)
		if err != nil {
			return nil, false, err
		}
		if runner != nil {
			return runner, false, nil
		}
	}
	if s.Sandboxes != nil {
		if err := s.Sandboxes.Ensure(ctx, inst, userID); err != nil {
			return nil, false, err
		}
	}
	runner, err := s.Runners.AliveRunner(ctx, s.RunnersAlive)
	if err != nil {
		return nil, false, err
	}
	if runner == nil {
		return nil, false, fmt.Errorf("no alive runner: %w", domain.ErrConflict)
	}
	queued, err := s.Client.Raise(ctx, runner.Address, inst.ID)
	if err != nil {
		return nil, false, fmt.Errorf("raise instance on runner %s: %w", runner.Name, err)
	}
	if queued {
		return runner, true, nil
	}
	if err := s.Instances.SetInstanceRunning(ctx, inst.ID, runner.ID); err != nil {
		return nil, false, err
	}
	return runner, false, nil
}
