"""Расшифровка полей hub.*_enc: AES-GCM, формат nonce(12) || ciphertext.

Ключ — SECRETS_KEY (64 hex-символа, 32 байта); тот же ключ использует backend при записи.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12


def decrypt(encrypted: bytes | None, key_hex: str) -> str | None:
    if encrypted is None:
        return None
    if not key_hex:
        raise ValueError("SECRETS_KEY is not set but an encrypted value is present")
    key = bytes.fromhex(key_hex)
    data = bytes(encrypted)
    plaintext = AESGCM(key).decrypt(data[:NONCE_SIZE], data[NONCE_SIZE:], None)
    return plaintext.decode()


def encrypt(plaintext: str, key_hex: str, *, nonce: bytes) -> bytes:
    """Обратная операция — для тестов и сидинга dev-данных."""
    key = bytes.fromhex(key_hex)
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), None)
