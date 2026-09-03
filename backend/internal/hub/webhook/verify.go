package webhook

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"strings"
)

// VerifyGitHub — HMAC-SHA256 тела запроса per-repo секретом против X-Hub-Signature-256.
func VerifyGitHub(body []byte, secret, sigHeader string) bool {
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

// VerifyGitLab — сравнение X-Gitlab-Token с per-repo секретом.
func VerifyGitLab(secret, tokenHeader string) bool {
	return tokenHeader != "" &&
		subtle.ConstantTimeCompare([]byte(secret), []byte(tokenHeader)) == 1
}
