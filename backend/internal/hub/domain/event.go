// Package domain — доменные типы и порты hub. Не зависит от HTTP, БД и брокера.
package domain

import (
	"encoding/json"
	"strconv"
	"strings"
	"time"
)

// Event — тонкий факт с вебхука (CONTEXT.md: Событие) до записи в БД.
type Event struct {
	DeliveryID string
	Action     string
	CommitSHA  string
	Ref        string
	TraceID    string // сквозной trace_id запроса, породившего Событие (pkg/trace)
}

// Repository — подключённый Репозиторий. Привязка Сборок — подписками
// (BuildSubscription, тикет 011); BuildID — derived-поле для deprecated
// wire-контракта (Сборка первой подписки), не колонка.
type Repository struct {
	ID                int64
	UserID            int64
	IdentityID        int64
	Provider          string
	ExternalID        string
	Owner             string
	Name              string
	DefaultBranch     *string
	WebhookProviderID *string
	WebhookSecretEnc  []byte
	BuildID           *int64
	ConnectedAt       time.Time
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

// EventMessage — тело сообщения в RabbitMQ (контракт тикета 010): тонкое
// Событие с готовыми id — Экземпляр отрезолвлен backend'ом на вебхуке,
// раннер тупо клеймит и исполняет. Без секретов и LLM-конфига.
func EventMessage(eventID, instanceID int64, threadID string, repo *Repository, e Event) []byte {
	b, _ := json.Marshal(map[string]any{
		"eventId":      eventID,
		"instanceId":   instanceID,
		"threadId":     threadID,
		"repositoryId": repo.ID,
		"provider":     repo.Provider,
		"action":       e.Action,
		"commitSha":    e.CommitSHA,
		"ref":          e.Ref,
		"dedupKey":     DedupKey(eventID, e),
		"traceId":      e.TraceID,
	})
	return b
}

// DedupKey — идемпотентность реакции Экземпляра (тикет 002):
// commit_sha для коммитных событий, иначе id События. full_scan НЕ привязан
// к коммиту: каждый запуск — отдельный прогон (ключ по id События), дубль
// защищается только подтверждением в UI.
func DedupKey(eventID int64, e Event) string {
	if e.Action == "full_scan" {
		return "full-" + strconv.FormatInt(eventID, 10)
	}
	if e.CommitSHA != "" {
		return e.CommitSHA
	}
	return strconv.FormatInt(eventID, 10)
}
