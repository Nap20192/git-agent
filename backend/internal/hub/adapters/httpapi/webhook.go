package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/trace"
)

const maxWebhookBody = 10 << 20

func (s *Server) webhook(w http.ResponseWriter, r *http.Request) {
	defer w.WriteHeader(http.StatusOK) // единственный ответ наружу
	log := trace.Logger(r.Context())

	provider := r.PathValue("provider")
	repoID, err := strconv.ParseInt(r.PathValue("repositoryId"), 10, 64)
	if (provider != "github" && provider != "gitlab") || err != nil {
		log.Infow("webhook: dropped, bad path", "provider", provider)
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, maxWebhookBody))
	if err != nil {
		log.Infow("webhook: dropped, body read", "err", err)
		return
	}
	e, ok := parseEvent(provider, r.Header, body)
	if !ok {
		log.Infow("webhook: dropped, unparseable event", "repositoryId", repoID, "provider", provider)
		return
	}
	auth := domain.WebhookAuth{
		GitHubSignature: r.Header.Get("X-Hub-Signature-256"),
		GitLabToken:     r.Header.Get("X-Gitlab-Token"),
	}
	s.Webhook.Handle(r.Context(), provider, repoID, auth, e, body)
}

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
			if forced, _ := p["forced"].(bool); !forced {
				e.BeforeSHA = beforeSHA(p)
			}
			e.ChangedFiles = changedFiles(p)
		case "pull_request":
			if pr, ok := dig(p, "pull_request"); ok {
				if head, ok := pr["head"].(map[string]any); ok {
					e.CommitSHA, _ = head["sha"].(string)
					e.Ref, _ = head["ref"].(string)
				}
				if base, ok := pr["base"].(map[string]any); ok {
					e.BaseSHA, _ = base["sha"].(string)
				}
				e.HeadSHA = e.CommitSHA
				e.PRNumber, e.PRTitle, e.PRBody = prMeta(pr, "number", "body")
			}
		}
	case "gitlab":
		e.DeliveryID = header.Get("X-Gitlab-Event-UUID")
		e.Action, _ = p["object_kind"].(string)
		if e.Action == "" {
			e.Action = strings.ReplaceAll(strings.ToLower(header.Get("X-Gitlab-Event")), " ", "_")
		}
		switch e.Action {
		case "push", "tag_push":
			e.CommitSHA, _ = p["checkout_sha"].(string)
			e.Ref, _ = p["ref"].(string)
			e.BeforeSHA = beforeSHA(p)
			e.ChangedFiles = changedFiles(p)
		case "merge_request":
			if attrs, ok := dig(p, "object_attributes"); ok {
				if last, ok := attrs["last_commit"].(map[string]any); ok {
					e.CommitSHA, _ = last["id"].(string)
				}
				e.Ref, _ = attrs["source_branch"].(string)
				e.HeadSHA = e.CommitSHA
				if refs, ok := attrs["diff_refs"].(map[string]any); ok {
					e.BaseSHA, _ = refs["base_sha"].(string)
					if head, _ := refs["head_sha"].(string); head != "" {
						e.HeadSHA = head
					}
				}
				e.PRNumber, e.PRTitle, e.PRBody = prMeta(attrs, "iid", "description")
			}
		}
	}
	return e, e.DeliveryID != "" && e.Action != ""
}

// beforeSHA — payload.before; нулевой sha (новая ветка) = диапазона нет.
func beforeSHA(p map[string]any) string {
	before, _ := p["before"].(string)
	if strings.Trim(before, "0") == "" {
		return ""
	}
	return before
}

// changedFiles — объединение added/modified/removed по payload.commits
// (GitHub и GitLab шлют одинаково), без дублей, в порядке появления.
func changedFiles(p map[string]any) []string {
	commits, _ := p["commits"].([]any)
	var out []string
	seen := map[string]bool{}
	for _, c := range commits {
		cm, _ := c.(map[string]any)
		for _, k := range []string{"added", "modified", "removed"} {
			files, _ := cm[k].([]any)
			for _, f := range files {
				if path, ok := f.(string); ok && !seen[path] {
					seen[path] = true
					out = append(out, path)
				}
			}
		}
	}
	return out
}

// prMeta — номер/заголовок/описание PR (GitHub: number/body, GitLab: iid/description);
// описание обрезается до domain.PRBodyMaxLen символов.
func prMeta(pr map[string]any, numberKey, bodyKey string) (int, string, string) {
	number, _ := pr[numberKey].(float64)
	title, _ := pr["title"].(string)
	body, _ := pr[bodyKey].(string)
	if r := []rune(body); len(r) > domain.PRBodyMaxLen {
		body = string(r[:domain.PRBodyMaxLen])
	}
	return int(number), title, body
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
