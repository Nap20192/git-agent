// Package domain — доменные типы и порты hub. Не зависит от HTTP, БД и брокера.
package domain

import (
	"encoding/json"
	"strconv"
	"strings"
)

// Event — тонкий факт с вебхука (CONTEXT.md: Событие) до записи в БД.
type Event struct {
	DeliveryID string
	Action     string
	CommitSHA  string
	Ref        string
}

// Repository — подключённый Репозиторий, как его видит вебхук-слой.
type Repository struct {
	ID               int64
	UserID           int64
	Provider         string
	Owner            string
	Name             string
	BuildID          *int64
	WebhookSecretEnc []byte
}

func (r *Repository) FullName() string { return r.Owner + "/" + r.Name }

// RoutingKey — `provider.repo.action` (тикет 005); repo — числовой id,
// потому что owner/name может содержать точки и ломать topic-сегменты.
func RoutingKey(provider string, repositoryID int64, action string) string {
	safe := strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '_' || r == '-' {
			return r
		}
		return '_'
	}, strings.ToLower(action))
	return provider + "." + strconv.FormatInt(repositoryID, 10) + "." + safe
}

// ThinPayload — тело События в RabbitMQ (тикет 001): без секретов и LLM-конфига.
func ThinPayload(eventID int64, repo *Repository, e Event) []byte {
	b, _ := json.Marshal(map[string]any{
		"eventId":      eventID,
		"provider":     repo.Provider,
		"repositoryId": repo.ID,
		"repo":         repo.FullName(),
		"action":       e.Action,
		"commitSha":    e.CommitSHA,
		"ref":          e.Ref,
		"userId":       repo.UserID,
	})
	return b
}

// DedupKey — идемпотентность реакции Экземпляра (тикет 002):
// commit_sha для коммитных событий, иначе id События.
func DedupKey(eventID int64, e Event) string {
	if e.CommitSHA != "" {
		return e.CommitSHA
	}
	return strconv.FormatInt(eventID, 10)
}
