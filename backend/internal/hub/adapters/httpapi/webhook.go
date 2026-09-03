// Package httpapi — inbound-адаптер HTTP: протокол провайдеров и wire-формат,
// вся политика — в app/domain.
package httpapi

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"

	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

const maxWebhookBody = 10 << 20

// WebhookHandler — POST /hooks/{provider}/{repositoryId} (тикет 002).
// Наружу ВСЕГДА 200: невалидная подпись, неизвестный репо, дубль — дроп + лог.
type WebhookHandler struct {
	Service *app.WebhookService
}

func (h *WebhookHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	defer w.WriteHeader(http.StatusOK) // единственный ответ наружу

	provider := r.PathValue("provider")
	repoID, err := strconv.ParseInt(r.PathValue("repositoryId"), 10, 64)
	if (provider != "github" && provider != "gitlab") || err != nil {
		slog.Info("webhook: dropped, bad path", "provider", provider)
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, maxWebhookBody))
	if err != nil {
		slog.Info("webhook: dropped, body read", "err", err)
		return
	}
	e, ok := parseEvent(provider, r.Header, body)
	if !ok {
		slog.Info("webhook: dropped, unparseable event", "repositoryId", repoID, "provider", provider)
		return
	}
	auth := domain.WebhookAuth{
		GitHubSignature: r.Header.Get("X-Hub-Signature-256"),
		GitLabToken:     r.Header.Get("X-Gitlab-Token"),
	}
	h.Service.Handle(r.Context(), provider, repoID, auth, e, body)
}

// parseEvent извлекает Событие из заголовков и JSON-тела провайдера.
// Неизвестные типы событий не ошибка: журналируем всё, commit/ref опциональны.
func parseEvent(provider string, header http.Header, body []byte) (domain.Event, bool) {
	var p map[string]any
	_ = json.Unmarshal(body, &p) // не-JSON тело → пустая map, Событие без commit/ref

	var e domain.Event
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
