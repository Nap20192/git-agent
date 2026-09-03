package domain

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

func githubSig(body []byte, secret string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return "sha256=" + hex.EncodeToString(mac.Sum(nil))
}

func TestVerifyWebhookGitHub(t *testing.T) {
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
		got := VerifyWebhook("github", tc.secret, tc.body, WebhookAuth{GitHubSignature: tc.header})
		if got != tc.want {
			t.Errorf("%s: got %v, want %v", name, got, tc.want)
		}
	}
}

func TestVerifyWebhookGitLab(t *testing.T) {
	if !VerifyWebhook("gitlab", "tok", nil, WebhookAuth{GitLabToken: "tok"}) {
		t.Error("matching token rejected")
	}
	if VerifyWebhook("gitlab", "tok", nil, WebhookAuth{GitLabToken: "wrong"}) {
		t.Error("wrong token accepted")
	}
	if VerifyWebhook("gitlab", "", nil, WebhookAuth{}) {
		t.Error("empty header accepted")
	}
}

func TestVerifyWebhookUnknownProvider(t *testing.T) {
	if VerifyWebhook("bitbucket", "s", nil, WebhookAuth{GitHubSignature: "x", GitLabToken: "s"}) {
		t.Error("unknown provider accepted")
	}
}
