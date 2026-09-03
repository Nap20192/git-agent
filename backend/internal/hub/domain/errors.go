package domain

import "errors"

var (
	ErrNotFound = errors.New("not found")
	// ErrConflict — нарушение инварианта: удаление связки с подключёнными
	// Репозиториями, подключение без свободного Раннера и т.п.
	ErrConflict = errors.New("conflict")
	// ErrUnauthorized — провайдер отверг токен (401): сигнал refresh-флоу.
	ErrUnauthorized = errors.New("unauthorized")
	// ErrUnavailable — фича не сконфигурирована (OAuth-ключи провайдера
	// не заданы): 503 с понятным текстом, сервис при этом стартует.
	ErrUnavailable = errors.New("unavailable")
	// ErrTimeout — раннер не начал отвечать за отведённое время
	// (он ставит запросы в очередь при занятых слотах): 504 наружу.
	ErrTimeout = errors.New("timeout")
)

// ErrUpstream — внешний сервис (провайдер) ответил ошибкой: 502 наружу,
// детали — только в лог.
var ErrUpstream = errors.New("upstream")

// ValidationError — отказ по входу. Единственный тип ошибки, чьё сообщение
// уходит клиенту как есть (400): текст пишет код, не внешняя система.
type ValidationError struct{ Msg string }

func (e *ValidationError) Error() string { return e.Msg }

// Invalid — ValidationError с текстом для клиента.
func Invalid(msg string) error { return &ValidationError{Msg: msg} }
