// Package config — env-конфиг hub. .env в корне монорепы, ключи не дублируем в коде.
package config

import (
	"encoding/hex"
	"fmt"
	"os"
	"strconv"
	"time"

	"go.uber.org/zap/zapcore"

	"github.com/joho/godotenv"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

type Config struct {
	DatabaseURL      string
	RunnerToken      string
	SecretsKey       []byte // 32 байта AES-256, в env — 64 hex-символа
	WebhookBaseURL   string
	RabbitMQURL      string
	Addr             string
	LogLevel         zapcore.Level // LOG_LEVEL=debug|info|warn|error (общий с раннером)
	HeartbeatTimeout time.Duration // раннер без heartbeat дольше — считается мёртвым

	// OAuth-приложения (тикет 003); пустые = провайдер недоступен (503), не ошибка старта
	GitHubOAuthID     string
	GitHubOAuthSecret string
	GitLabOAuthID     string
	GitLabOAuthSecret string
	FrontendURL       string // redirect после входа
	// OAuthRedirectBase — базовый URL для OAuth redirect_uri (должен совпадать с
	// callback в OAuth App). В dev это localhost, а WebhookBaseURL — публичный
	// туннель для вебхуков; их надо разводить. Пусто ⇒ из хоста запроса.
	OAuthRedirectBase string

	ChatFirstByteTimeout time.Duration // ожидание первого байта SSE от раннера

	// Defaults — чем заполнять пустые поля при создании подключений/сборок
	// (LLM_API_BASE, LLM_MODEL, OPENSANDBOX_DOMAIN, OPENSANDBOX_API_KEY, SANDBOX_IMAGE).
	Defaults domain.Defaults

	DevUserID int64 // DEV_USER_ID: dev-обход OAuth — запросы без сессии идут от этого user id; 0 = выключено
}

// Load читает .env (корень монорепы либо cwd) и собирает конфиг.
// Отсутствие обязательного ключа — ошибка на старте, не в рантайме.
func Load() (*Config, error) {
	for _, p := range []string{".env", "../.env"} {
		if err := godotenv.Load(p); err == nil {
			break
		}
	}

	c := &Config{
		DatabaseURL:       os.Getenv("DATABASE_URL"),
		RunnerToken:       os.Getenv("RUNNER_TOKEN"),
		WebhookBaseURL:    os.Getenv("WEBHOOK_BASE_URL"),
		RabbitMQURL:       os.Getenv("RABBITMQ_URL"),
		Addr:              os.Getenv("HUB_ADDR"),
		GitHubOAuthID:     os.Getenv("GITHUB_OAUTH_CLIENT_ID"),
		GitHubOAuthSecret: os.Getenv("GITHUB_OAUTH_CLIENT_SECRET"),
		GitLabOAuthID:     os.Getenv("GITLAB_OAUTH_CLIENT_ID"),
		GitLabOAuthSecret: os.Getenv("GITLAB_OAUTH_CLIENT_SECRET"),
		FrontendURL:       os.Getenv("FRONTEND_URL"),
		OAuthRedirectBase: os.Getenv("OAUTH_REDIRECT_BASE"),
		Defaults: domain.Defaults{
			LlmAPIBase:    os.Getenv("LLM_API_BASE"),
			LlmModel:      os.Getenv("LLM_MODEL"),
			SandboxDomain: os.Getenv("OPENSANDBOX_DOMAIN"),
			SandboxAPIKey: os.Getenv("OPENSANDBOX_API_KEY"),
			SandboxImage:  os.Getenv("SANDBOX_IMAGE"),
		},
	}
	if c.Defaults.SandboxDomain == "" {
		c.Defaults.SandboxDomain = "localhost:8090" // зеркало agent/core/config.py
	}
	if c.Defaults.SandboxImage == "" {
		c.Defaults.SandboxImage = "git-agent/sandbox:strix"
	}
	if c.Addr == "" {
		c.Addr = ":8081"
	}
	if v := os.Getenv("LOG_LEVEL"); v != "" {
		if err := c.LogLevel.UnmarshalText([]byte(v)); err != nil {
			return nil, fmt.Errorf("config: LOG_LEVEL %q: %w", v, err)
		}
	}
	if c.FrontendURL == "" {
		c.FrontendURL = "http://localhost:5173"
	}
	if c.RabbitMQURL == "" {
		c.RabbitMQURL = "amqp://guest:guest@localhost:5673/"
	}
	c.HeartbeatTimeout = 30 * time.Second
	if v := os.Getenv("HEARTBEAT_TIMEOUT_SECONDS"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 {
			return nil, fmt.Errorf("config: HEARTBEAT_TIMEOUT_SECONDS must be a positive integer")
		}
		c.HeartbeatTimeout = time.Duration(n) * time.Second
	}
	// раннер при занятых слотах ставит чат в очередь — ждём щедро
	c.ChatFirstByteTimeout = 120 * time.Second
	if v := os.Getenv("CHAT_FIRST_BYTE_TIMEOUT_SECONDS"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 {
			return nil, fmt.Errorf("config: CHAT_FIRST_BYTE_TIMEOUT_SECONDS must be a positive integer")
		}
		c.ChatFirstByteTimeout = time.Duration(n) * time.Second
	}
	if v := os.Getenv("DEV_USER_ID"); v != "" {
		n, err := strconv.ParseInt(v, 10, 64)
		if err != nil || n < 1 {
			return nil, fmt.Errorf("config: DEV_USER_ID must be a positive integer")
		}
		c.DevUserID = n
	}
	for name, v := range map[string]string{
		"DATABASE_URL": c.DatabaseURL,
		"RUNNER_TOKEN": c.RunnerToken,
	} {
		if v == "" {
			return nil, fmt.Errorf("config: %s is required", name)
		}
	}
	key, err := hex.DecodeString(os.Getenv("SECRETS_KEY"))
	if err != nil || len(key) != 32 {
		return nil, fmt.Errorf("config: SECRETS_KEY must be 64 hex chars (32-byte AES key)")
	}
	c.SecretsKey = key
	return c, nil
}
