"""AES-256-GCM helpers for sensitive at-rest fields."""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


def _derive_key() -> bytes:
    raw = (settings.DATA_ENCRYPTION_KEY or "").encode("utf-8")
    if not raw:
        raise RuntimeError("DATA_ENCRYPTION_KEY is not configured")
    # Derive a 32-byte AES-256 key deterministically from the configured secret.
    return hashlib.sha256(raw).digest()


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string. Returns ``v1.<key_id>.<nonce_b64>.<ct_b64>``.

    The key id is included so re-keying/rotation can be detected on read.
    """
    if plaintext is None:
        raise ValueError("plaintext required")
    key = _derive_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return "v1.{kid}.{n}.{c}".format(
        kid=settings.DATA_ENCRYPTION_KEY_ID,
        n=base64.b64encode(nonce).decode("ascii"),
        c=base64.b64encode(ct).decode("ascii"),
    )


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`."""
    if not token:
        raise ValueError("token required")
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "v1":
        raise ValueError("unrecognized ciphertext envelope")
    _, _kid, n_b64, c_b64 = parts
    key = _derive_key()
    nonce = base64.b64decode(n_b64)
    ct = base64.b64decode(c_b64)
    pt = AESGCM(key).decrypt(nonce, ct, associated_data=None)
    return pt.decode("utf-8")
