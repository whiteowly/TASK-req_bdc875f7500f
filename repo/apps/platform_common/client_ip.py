"""Centralized client IP extraction with a single trust model.

The project runs behind an nginx reverse proxy that sets ``X-Real-IP`` from
``$remote_addr`` (the actual TCP peer). This header **cannot** be forged by
the client because nginx overwrites it unconditionally.

We do **not** trust ``X-Forwarded-For`` for primary identity because a client
can prepend arbitrary IPs to that header.

Trust order:
1. ``X-Real-IP`` (set by trusted proxy)
2. ``REMOTE_ADDR`` (Django / WSGI peer address)
"""
from __future__ import annotations


def client_ip(request) -> str:
    """Return the best-effort real client IP from *request*.

    Used by rate limiting **and** audit logging so both subsystems share
    the same trust model.
    """
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    return request.META.get("REMOTE_ADDR", "")
