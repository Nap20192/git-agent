package webhook

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"testing"
)

func githubSig(body []byte, secret string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return "sha256=" + hex.EncodeToString(mac.Sum(nil))
}

func TestVerifyGitHub(t *testing.T) {
	body := []byte(`{"after":"abc"}`)
	sig := githubSig(body, "s3cret")
	for name, tc := range map[string]struct {
		body   []byte
		secret string
		header string
		want   bool
	}{
		"valid":         {body, "s3cret", sig, true},
		"wrong secret":  {body, "other", sig, false},
		"tampered body": {[]byte(`{"after":"xyz"}`), "s3cret", sig, false},
		"no prefix":     {body, "s3cret", sig[len("sha256="):], false},
		"bad hex":       {body, "s3cret", "sha256=zzzz", false},
		"empty header":  {body, "s3cret", "", false},
	} {
		if got := VerifyGitHub(tc.body, tc.secret, tc.header); got != tc.want {
			t.Errorf("%s: got %v, want %v", name, got, tc.want)
		}
	}
}

func TestVerifyGitLab(t *testing.T) {
	if !VerifyGitLab("tok", "tok") {
		t.Error("matching token rejected")
	}
	if VerifyGitLab("tok", "wrong") {
		t.Error("wrong token accepted")
	}
	if VerifyGitLab("", "") {
		t.Error("empty header accepted")
	}
}

func TestParseGitHubPush(t *testing.T) {
	h := http.Header{}
	h.Set("X-GitHub-Delivery", "d-1")
	h.Set("X-GitHub-Event", "push")
	e, ok := Parse("github", h, []byte(`{"after":"abc123","ref":"refs/heads/main"}`))
	if !ok || e.DeliveryID != "d-1" || e.Action != "push" || e.CommitSHA != "abc123" || e.Ref != "refs/heads/main" {
		t.Errorf("got %+v ok=%v", e, ok)
	}
}

func TestParseGitHubPullRequest(t *testing.T) {
	h := http.Header{}
	h.Set("X-GitHub-Delivery", "d-2")
	h.Set("X-GitHub-Event", "pull_request")
	e, ok := Parse("github", h, []byte(`{"pull_request":{"head":{"sha":"def456","ref":"feature"}}}`))
	if !ok || e.CommitSHA != "def456" || e.Ref != "feature" {
		t.Errorf("got %+v ok=%v", e, ok)
	}
}

func TestParseGitLabPush(t *testing.T) {
	h := http.Header{}
	h.Set("X-Gitlab-Event-UUID", "u-1")
	e, ok := Parse("gitlab", h, []byte(`{"object_kind":"push","checkout_sha":"abc","ref":"refs/heads/main"}`))
	if !ok || e.Action != "push" || e.CommitSHA != "abc" {
		t.Errorf("got %+v ok=%v", e, ok)
	}
}

func TestParseGitLabMergeRequest(t *testing.T) {
	h := http.Header{}
	h.Set("X-Gitlab-Event-UUID", "u-2")
	e, ok := Parse("gitlab", h,
		[]byte(`{"object_kind":"merge_request","object_attributes":{"source_branch":"feat","last_commit":{"id":"c0ffee"}}}`))
	if !ok || e.CommitSHA != "c0ffee" || e.Ref != "feat" {
		t.Errorf("got %+v ok=%v", e, ok)
	}
}

func TestParseMissingDelivery(t *testing.T) {
	h := http.Header{}
	h.Set("X-GitHub-Event", "push")
	if _, ok := Parse("github", h, []byte(`{}`)); ok {
		t.Error("event without delivery id accepted")
	}
}

func TestRoutingKey(t *testing.T) {
	if got := RoutingKey("github", 42, "push"); got != "github.42.push" {
		t.Errorf("got %q", got)
	}
	// точки и пробелы в action не должны ломать topic-сегменты
	if got := RoutingKey("gitlab", 7, "Push Hook"); got != "gitlab.7.push_hook" {
		t.Errorf("got %q", got)
	}
}
