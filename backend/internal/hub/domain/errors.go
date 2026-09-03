package domain

import "errors"

var (
	ErrNotFound = errors.New("not found")
	// ErrConflict — нарушение инварианта: удаление связки с подключёнными
	// Репозиториями, подключение без свободного Раннера и т.п.
	ErrConflict = errors.New("conflict")
)
