// Package postgres — клиент БД по образцу go-coffeeshop/pkg/postgres,
// адаптирован под pgx/v5 (pgxpool вместо database/sql).
package postgres

import (
	"context"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	_defaultConnAttempts = 3
	_defaultConnTimeout  = time.Second
)

type DBConnString string

type postgres struct {
	connAttempts int
	connTimeout  time.Duration

	pool *pgxpool.Pool
}

var _ DBEngine = (*postgres)(nil)

func NewPostgresDB(ctx context.Context, url DBConnString, opts ...Option) (DBEngine, error) {
	pg := &postgres{
		connAttempts: _defaultConnAttempts,
		connTimeout:  _defaultConnTimeout,
	}
	for _, opt := range opts {
		opt(pg)
	}

	var err error
	for pg.connAttempts > 0 {
		if pg.pool, err = pgxpool.New(ctx, string(url)); err == nil {
			if err = pg.pool.Ping(ctx); err == nil {
				break
			}
			pg.pool.Close()
		}
		pg.connAttempts--
		slog.Info("postgres is trying to connect", "attempts left", pg.connAttempts, "err", err)
		time.Sleep(pg.connTimeout)
	}
	if err != nil {
		return nil, err
	}

	slog.Info("📰 connected to postgresdb 🎉")
	return pg, nil
}

func (p *postgres) GetDB() *pgxpool.Pool {
	return p.pool
}

func (p *postgres) Close() {
	if p.pool != nil {
		p.pool.Close()
	}
}
