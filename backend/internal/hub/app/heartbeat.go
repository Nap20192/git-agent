package app

import (
	"context"
	"time"

	"go.uber.org/zap"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// HeartbeatService — надзор за Раннерами (тикеты 004/005): раннер без
// heartbeat дольше Timeout ⇒ его running-Экземпляры → down, их необработанные
// События — снова в outbox (ре-публикация, дубли гасит дедуп Экземпляра).
type HeartbeatService struct {
	Store    domain.StaleRequeuer
	Timeout  time.Duration
	Interval time.Duration
}

func (s *HeartbeatService) Run(ctx context.Context) error {
	interval := s.Interval
	if interval == 0 {
		interval = s.Timeout / 2
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			downed, requeued, err := s.Store.RequeueStale(ctx, s.Timeout)
			if err != nil {
				zap.S().Errorw("heartbeat: requeue failed", "err", err)
				continue
			}
			if downed > 0 || requeued > 0 {
				zap.S().Infow("heartbeat: stale runners handled", "instancesDowned", downed, "eventsRequeued", requeued)
			}
		}
	}
}
