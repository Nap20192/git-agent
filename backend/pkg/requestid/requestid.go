// Package requestid — сквозной X-Request-ID: hub-middleware кладёт его в ctx,
// runnerapi-клиент передаёт раннеру, тот привязывает к своим логам.
package requestid

import "context"

type ctxKey struct{}

func WithValue(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, ctxKey{}, id)
}

// FromContext — id из контекста, "" если нет.
func FromContext(ctx context.Context) string {
	id, _ := ctx.Value(ctxKey{}).(string)
	return id
}

// Valid — чужой X-Request-ID берём только короткий и печатный: заголовок
// недоверенный, а попадёт в лог и в ответ как есть.
func Valid(id string) bool {
	if id == "" || len(id) > 64 {
		return false
	}
	for _, c := range id {
		if c <= ' ' || c > '~' {
			return false
		}
	}
	return true
}
