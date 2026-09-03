"""Расшифровка полей hub.*_enc: AES-GCM, формат nonce(12) || ciphertext.

Ключ — HUB_ENC_KEY (base64, 32 байта); тот же ключ использует backend при записи.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12


def decrypt(encrypted: bytes | None, key_b64: str) -> str | None:
    if encrypted is None:
        return None
    if not key_b64:
        raise ValueError("HUB_ENC_KEY is not set but an encrypted value is present")
    key = base64.b64decode(key_b64)
    data = bytes(encrypted)
    plaintext = AESGCM(key).decrypt(data[:NONCE_SIZE], data[NONCE_SIZE:], None)
    return plaintext.decode()


def encrypt(plaintext: str, key_b64: str, *, nonce: bytes) -> bytes:
    """Обратная операция — для тестов и сидинга dev-данных."""
    key = base64.b64decode(key_b64)
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), None)
