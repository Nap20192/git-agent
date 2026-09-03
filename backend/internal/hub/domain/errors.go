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
	// ErrInvalid — невалидный ввод: 400, текст обёртки уходит клиенту.
	ErrInvalid = errors.New("invalid")
	// ErrUpstream — внешняя система (провайдер, Раннер, OpenSandbox) не
	// ответила или ответила ошибкой: 502, текст обёртки уходит клиенту.
	ErrUpstream = errors.New("upstream")
)
