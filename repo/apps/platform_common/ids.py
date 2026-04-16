"""Stable internal ID generation (ULID-like, lexicographically sortable)."""
from __future__ import annotations

import os
import time

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    """Return ``<prefix>_<26-char ULID>``.

    Uses 48 bits of millisecond timestamp and 80 bits of randomness, encoded
    in Crockford base32 — 26 characters total.
    """
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    return f"{prefix}_{_encode(ts_ms, 10)}{_encode(rand, 16)}"
