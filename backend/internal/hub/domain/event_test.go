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

func TestThinPayload(t *testing.T) {
	uid := int64(3)
	repo := &Repository{ID: 42, UserID: uid, Provider: "github", Owner: "acme", Name: "repo"}
	var got map[string]any
	if err := json.Unmarshal(ThinPayload(7, repo, Event{Action: "push", CommitSHA: "abc", Ref: "refs/heads/main"}), &got); err != nil {
		t.Fatal(err)
	}
	for k, want := range map[string]any{
		"eventId": float64(7), "provider": "github", "repositoryId": float64(42),
		"repo": "acme/repo", "action": "push", "commitSha": "abc", "userId": float64(3),
	} {
		if got[k] != want {
			t.Errorf("%s: got %v, want %v", k, got[k], want)
		}
	}
}
