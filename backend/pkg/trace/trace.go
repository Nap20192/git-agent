// Package trace — сквозной trace_id (32 hex, uuid4 без дефисов): фронт/вебхук →
// hub-middleware (принять из X-Trace-Id либо сгенерировать) → ctx → логи,
// hub.events/hub.activity, traceId в Rabbit-сообщении, заголовок в раннер и
// провайдеры. Один id собирает всё, что происходило с запросом/Событием.
package trace

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"strings"

	"go.uber.org/zap"
)

const (
	Header = "X-Trace-Id"
	Field  = "trace_id" // имя поля в логах — одно на все три сервиса
)

type ctxKey struct{}

// New — uuid4 без дефисов.
func New() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic(err) // crypto/rand не отказывает
	}
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	return hex.EncodeToString(b[:])
}

// Valid — чужой заголовок берём только в нашем формате: он уйдёт в лог, в БД и в ответ как есть.
func Valid(id string) bool {
	if len(id) != 32 {
		return false
	}
	for _, c := range id {
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') && (c < 'A' || c > 'F') {
			return false
		}
	}
	return true
}

// Accept — входящий заголовок, если валиден (в нижнем регистре), иначе новый id.
func Accept(header string) string {
	if Valid(header) {
		return strings.ToLower(header)
	}
	return New()
}

func WithValue(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, ctxKey{}, id)
}

// FromContext — id из контекста, "" если нет.
func FromContext(ctx context.Context) string {
	id, _ := ctx.Value(ctxKey{}).(string)
	return id
}

// Logger — глобальный zap с trace_id из ctx; единственный способ логировать в
// пути запроса (руками поле не добавлять).
func Logger(ctx context.Context) *zap.SugaredLogger {
	if id := FromContext(ctx); id != "" {
		return zap.S().With(Field, id)
	}
	return zap.S()
}

// FromMessage — traceId из JSON-сообщения События (outbox/Rabbit).
func FromMessage(payload []byte) string {
	var m struct {
		TraceID string `json:"traceId"`
	}
	_ = json.Unmarshal(payload, &m)
	return m.TraceID
}
