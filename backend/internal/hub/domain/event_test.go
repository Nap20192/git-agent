package domain

import (
	"encoding/json"
	"testing"
)

func TestRoutingKey(t *testing.T) {
	if got := RoutingKey("github", 42, "push"); got != "github.42.push" {
		t.Errorf("got %q", got)
	}
	// точки и пробелы в action не должны ломать topic-сегменты
	if got := RoutingKey("gitlab", 7, "Push Hook"); got != "gitlab.7.push_hook" {
		t.Errorf("got %q", got)
	}
}

func TestDedupKey(t *testing.T) {
	if got := DedupKey(5, Event{CommitSHA: "abc"}); got != "abc" {
		t.Errorf("commit event: got %q", got)
	}
	if got := DedupKey(5, Event{}); got != "5" {
		t.Errorf("commitless event: got %q", got)
	}
}

// Контракт сообщения — тикет 010: готовые id, dedupKey, без секретов.
func TestEventMessage(t *testing.T) {
	repo := &Repository{ID: 42, UserID: 3, Provider: "github", Owner: "acme", Name: "repo"}
	var got map[string]any
	msg := EventMessage(7, 15, "hub-9-42", repo, Event{Action: "push", CommitSHA: "abc", Ref: "refs/heads/main"})
	if err := json.Unmarshal(msg, &got); err != nil {
		t.Fatal(err)
	}
	for k, want := range map[string]any{
		"eventId": float64(7), "instanceId": float64(15), "threadId": "hub-9-42",
		"repositoryId": float64(42), "provider": "github", "action": "push",
		"commitSha": "abc", "ref": "refs/heads/main", "dedupKey": "abc",
	} {
		if got[k] != want {
			t.Errorf("%s: got %v, want %v", k, got[k], want)
		}
	}
}
