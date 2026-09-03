package app

import (
	"context"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// ConnectionService — LLM/sandbox-подключения: ключи хранятся шифром
// (AES-GCM, secrets.Box). Инвариант redaction: ключ наружу ТОЛЬКО маской
// (MaskKey) — зеркало agent/infra/server/wire.py::mask_key.
type ConnectionService struct {
	Store   domain.ConnectionStore
	Secrets *secrets.Box
}

// MaskKey — «…» + последние 4 символа; короткий ключ — просто «…».
func MaskKey(key string) string {
	if key == "" {
		return ""
	}
	if len(key) > 4 {
		return "…" + key[len(key)-4:]
	}
	return "…"
}

// MaskedKey — маска расшифрованного ключа; нерасшифровываемый — «…»
// (не повод отдать 500 на листинге), nil — пустая строка.
func (s *ConnectionService) MaskedKey(enc []byte) string {
	if enc == nil {
		return ""
	}
	key, err := s.Secrets.Decrypt(enc)
	if err != nil {
		return "…"
	}
	return MaskKey(string(key))
}

// CreateLlm шифрует apiKey в c.APIKeyEnc и сохраняет подключение.
func (s *ConnectionService) CreateLlm(ctx context.Context, c *domain.LlmConnection, apiKey string) (int64, error) {
	enc, err := s.Secrets.Encrypt([]byte(apiKey))
	if err != nil {
		return 0, err
	}
	c.APIKeyEnc = enc
	return s.Store.CreateLlmConnection(ctx, c)
}

// CreateSandbox — пустой apiKey = подключение без ключа.
func (s *ConnectionService) CreateSandbox(ctx context.Context, c *domain.SandboxConnection, apiKey string) (int64, error) {
	if apiKey != "" {
		enc, err := s.Secrets.Encrypt([]byte(apiKey))
		if err != nil {
			return 0, err
		}
		c.APIKeyEnc = enc
	}
	return s.Store.CreateSandboxConnection(ctx, c)
}
