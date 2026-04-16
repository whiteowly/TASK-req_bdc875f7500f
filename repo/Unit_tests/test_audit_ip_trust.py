"""Audit IP extraction uses the same trust model as rate limiting.

Proves that:
- Audit logging uses X-Real-IP (not X-Forwarded-For) for primary identity.
- Spoofed X-Forwarded-For is ignored by audit.
- Both audit and rate-limit share the centralized client_ip helper.
"""
from __future__ import annotations

import pytest

from apps.platform_common.client_ip import client_ip
from apps.platform_common.middleware import RateLimitMiddleware


class _FakeRequest:
    def __init__(self, headers=None, meta=None):
        self._headers = headers or {}
        self.META = meta or {}

    @property
    def headers(self):
        return self._headers


pytestmark = pytest.mark.no_db


def test_audit_ip_uses_x_real_ip():
    req = _FakeRequest(
        headers={"X-Real-IP": "10.0.0.1", "X-Forwarded-For": "9.9.9.9, 10.0.0.1"},
        meta={"REMOTE_ADDR": "172.17.0.2"},
    )
    assert client_ip(req) == "10.0.0.1"


def test_audit_ip_ignores_spoofed_x_forwarded_for():
    """A malicious client sends X-Forwarded-For: 8.8.8.8 but no X-Real-IP.
    Audit must use REMOTE_ADDR, not the spoofed header."""
    req = _FakeRequest(
        headers={"X-Forwarded-For": "8.8.8.8"},
        meta={"REMOTE_ADDR": "192.168.1.50"},
    )
    assert client_ip(req) == "192.168.1.50"


def test_audit_ip_falls_back_to_remote_addr():
    req = _FakeRequest(headers={}, meta={"REMOTE_ADDR": "10.10.10.10"})
    assert client_ip(req) == "10.10.10.10"


def test_audit_and_rate_limit_share_same_helper():
    """Both subsystems must return the same IP for the same request."""
    req = _FakeRequest(
        headers={"X-Real-IP": "203.0.113.5", "X-Forwarded-For": "1.2.3.4"},
        meta={"REMOTE_ADDR": "172.18.0.3"},
    )
    audit_ip = client_ip(req)
    rate_limit_ip = RateLimitMiddleware._client_ip(req)
    assert audit_ip == rate_limit_ip == "203.0.113.5"


def test_audit_and_rate_limit_both_ignore_xff_when_no_real_ip():
    req = _FakeRequest(
        headers={"X-Forwarded-For": "6.6.6.6"},
        meta={"REMOTE_ADDR": "10.20.30.40"},
    )
    audit_ip = client_ip(req)
    rate_limit_ip = RateLimitMiddleware._client_ip(req)
    assert audit_ip == rate_limit_ip == "10.20.30.40"
