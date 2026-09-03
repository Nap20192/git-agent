// hub — Go-бекенд git-agent: вебхуки, outbox→RabbitMQ, реестр раннеров.
// Граф зависимостей собирает internal/hub/container (фабрика New),
// сервисы бегут в errgroup с graceful shutdown. Спека: .wayfinder/map.md.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/vnkjd/git-agent/backend/pkg/dnsfix"
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"

	"github.com/vnkjd/git-agent/backend/cmd/hub/config"
	"github.com/vnkjd/git-agent/backend/internal/hub/container"
)

func main() {
	zap.ReplaceGlobals(newLogger(zapcore.InfoLevel)) // до чтения конфига
	if err := run(); err != nil {
		zap.S().Errorw("hub: fatal", "err", err)
		os.Exit(1)
	}
}

// newLogger — HUB_ENV=prod → JSON-продакшен, иначе dev-консоль; порог — LOG_LEVEL.
func newLogger(level zapcore.Level) *zap.Logger {
	cfg := zap.NewDevelopmentConfig()
	if os.Getenv("HUB_ENV") == "prod" {
		cfg = zap.NewProductionConfig()
	}
	cfg.Level = zap.NewAtomicLevelAt(level)
	// стек — у паник (Recover) и Fatal, не у каждой обработанной ошибки: иначе 502 выглядит как крэш
	cfg.DisableStacktrace = true
	return zap.Must(cfg.Build())
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	dnsfix.Install(os.Getenv("DNS_SERVER")) // dev: обход сломанного системного резолвера
	logger := newLogger(cfg.LogLevel)
	defer logger.Sync() //nolint:errcheck // stderr
	zap.ReplaceGlobals(logger)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	c, err := container.New(ctx, cfg)
	if err != nil {
		return err
	}
	defer c.Close()

	return c.Run(ctx)
}
