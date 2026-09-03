// Package secrets — AES-GCM шифрование секретных полей БД (*_enc). Формат: nonce || ciphertext.
package secrets

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"fmt"
)

type Box struct{ aead cipher.AEAD }

func New(key []byte) (*Box, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return &Box{aead}, nil
}

func (b *Box) Encrypt(plaintext []byte) ([]byte, error) {
	nonce := make([]byte, b.aead.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return nil, err
	}
	return b.aead.Seal(nonce, nonce, plaintext, nil), nil
}

func (b *Box) Decrypt(data []byte) ([]byte, error) {
	ns := b.aead.NonceSize()
	if len(data) < ns {
		return nil, fmt.Errorf("secrets: ciphertext too short")
	}
	return b.aead.Open(nil, data[:ns], data[ns:], nil)
}
