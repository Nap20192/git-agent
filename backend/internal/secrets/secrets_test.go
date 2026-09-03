package secrets

import (
	"bytes"
	"testing"
)

func TestRoundtrip(t *testing.T) {
	box, err := New(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	enc, err := box.Encrypt([]byte("webhook-secret"))
	if err != nil {
		t.Fatal(err)
	}
	dec, err := box.Decrypt(enc)
	if err != nil || string(dec) != "webhook-secret" {
		t.Fatalf("got %q, err=%v", dec, err)
	}
	// два шифрования одного текста различаются (случайный nonce)
	enc2, _ := box.Encrypt([]byte("webhook-secret"))
	if bytes.Equal(enc, enc2) {
		t.Error("nonce reuse")
	}
}

func TestTamperDetected(t *testing.T) {
	box, _ := New(bytes.Repeat([]byte{7}, 32))
	enc, _ := box.Encrypt([]byte("x"))
	enc[len(enc)-1] ^= 1
	if _, err := box.Decrypt(enc); err == nil {
		t.Error("tampered ciphertext accepted")
	}
	if _, err := box.Decrypt([]byte("short")); err == nil {
		t.Error("short ciphertext accepted")
	}
}
