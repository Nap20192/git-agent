package domain

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"strings"
)

// WebhookAuth — предъявленные провайдером учётные данные доставки.
type WebhookAuth struct {
	GitHubSignature string // X-Hub-Signature-256
	GitLabToken     string // X-Gitlab-Token
}

// VerifyWebhook — подлинность доставки per-repo секретом.
func VerifyWebhook(provider string, secret string, body []byte, auth WebhookAuth) bool {
	switch provider {
	case "github":
		return verifyGitHub(body, secret, auth.GitHubSignature)
	case "gitlab":
		return verifyGitLab(secret, auth.GitLabToken)
	}
	return false
}

// verifyGitHub — HMAC-SHA256 тела запроса per-repo секретом против X-Hub-Signature-256.
func verifyGitHub(body []byte, secret, sigHeader string) bool {
	hexSig, ok := strings.CutPrefix(sigHeader, "sha256=")
	if !ok {
		return false
	}
	sig, err := hex.DecodeString(hexSig)
	if err != nil {
		return false
	}
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return hmac.Equal(sig, mac.Sum(nil))
}

// verifyGitLab — сравнение X-Gitlab-Token с per-repo секретом.
func verifyGitLab(secret, tokenHeader string) bool {
	return tokenHeader != "" &&
		subtle.ConstantTimeCompare([]byte(secret), []byte(tokenHeader)) == 1
}
