// Package config — env-конфиг hub. .env в корне монорепы, ключи не дублируем в коде.
package config

import (
	"encoding/hex"
	"fmt"
	"os"

	"github.com/joho/godotenv"
)

type Config struct {
	DatabaseURL    string
	RunnerToken    string
	SecretsKey     []byte // 32 байта AES-256, в env — 64 hex-символа
	WebhookBaseURL string
	RabbitMQURL    string
	Addr           string
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
		DatabaseURL:    os.Getenv("DATABASE_URL"),
		RunnerToken:    os.Getenv("RUNNER_TOKEN"),
		WebhookBaseURL: os.Getenv("WEBHOOK_BASE_URL"),
		RabbitMQURL:    os.Getenv("RABBITMQ_URL"),
		Addr:           os.Getenv("HUB_ADDR"),
	}
	if c.Addr == "" {
		c.Addr = ":8081"
	}
	if c.RabbitMQURL == "" {
		c.RabbitMQURL = "amqp://guest:guest@localhost:5673/"
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
