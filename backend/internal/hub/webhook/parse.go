package webhook

import (
	"encoding/json"
	"net/http"
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

// Parse извлекает Событие из заголовков и JSON-тела провайдера.
// Неизвестные типы событий не ошибка: журналируем всё, commit/ref опциональны.
func Parse(provider string, header http.Header, body []byte) (Event, bool) {
	var p map[string]any
	_ = json.Unmarshal(body, &p) // не-JSON тело → пустая map, Событие без commit/ref

	var e Event
	switch provider {
	case "github":
		e.DeliveryID = header.Get("X-GitHub-Delivery")
		e.Action = header.Get("X-GitHub-Event")
		switch e.Action {
		case "push":
			e.CommitSHA, _ = p["after"].(string)
			e.Ref, _ = p["ref"].(string)
		case "pull_request":
			if head, ok := dig(p, "pull_request", "head"); ok {
				e.CommitSHA, _ = head["sha"].(string)
				e.Ref, _ = head["ref"].(string)
			}
		}
	case "gitlab":
		e.DeliveryID = header.Get("X-Gitlab-Event-UUID")
		e.Action, _ = p["object_kind"].(string)
		if e.Action == "" {
			// системные хуки без object_kind — нормализованный заголовок события
			e.Action = strings.ReplaceAll(strings.ToLower(header.Get("X-Gitlab-Event")), " ", "_")
		}
		switch e.Action {
		case "push", "tag_push":
			e.CommitSHA, _ = p["checkout_sha"].(string)
			e.Ref, _ = p["ref"].(string)
		case "merge_request":
			if attrs, ok := dig(p, "object_attributes"); ok {
				if last, ok := attrs["last_commit"].(map[string]any); ok {
					e.CommitSHA, _ = last["id"].(string)
				}
				e.Ref, _ = attrs["source_branch"].(string)
			}
		}
	}
	return e, e.DeliveryID != "" && e.Action != ""
}

func dig(m map[string]any, keys ...string) (map[string]any, bool) {
	for _, k := range keys {
		next, ok := m[k].(map[string]any)
		if !ok {
			return nil, false
		}
		m = next
	}
	return m, true
}

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
