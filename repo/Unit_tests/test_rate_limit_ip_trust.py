"""Rate-limit IP trust model: X-Real-IP is trusted, X-Forwarded-For is not.

Proves that a spoofed X-Forwarded-For header does NOT change the IP used
for per-IP rate limiting, while X-Real-IP (set by our nginx proxy) does.
"""
import pytest

from apps.platform_common.middleware import RateLimitMiddleware


class _FakeRequest:
    def __init__(self, headers=None, meta=None):
        self._headers = headers or {}
        self.META = meta or {}

    @property
    def headers(self):
        return self._headers


pytestmark = pytest.mark.no_db


def test_uses_x_real_ip_when_present():
    req = _FakeRequest(
        headers={"X-Real-IP": "10.0.0.1", "X-Forwarded-For": "1.2.3.4, 10.0.0.1"},
        meta={"REMOTE_ADDR": "172.17.0.2"},
    )
    assert RateLimitMiddleware._client_ip(req) == "10.0.0.1"


def test_ignores_spoofed_x_forwarded_for():
    """Client sends X-Forwarded-For: 9.9.9.9 to masquerade as a different IP.
    The rate limiter must use REMOTE_ADDR, not the spoofed header."""
    req = _FakeRequest(
        headers={"X-Forwarded-For": "9.9.9.9"},
        meta={"REMOTE_ADDR": "192.168.1.42"},
    )
    # X-Real-IP is absent → falls back to REMOTE_ADDR, not X-Forwarded-For.
    assert RateLimitMiddleware._client_ip(req) == "192.168.1.42"


def test_falls_back_to_remote_addr_when_no_proxy_header():
    req = _FakeRequest(headers={}, meta={"REMOTE_ADDR": "10.10.10.10"})
    assert RateLimitMiddleware._client_ip(req) == "10.10.10.10"


def test_empty_x_real_ip_ignored():
    req = _FakeRequest(
        headers={"X-Real-IP": "", "X-Forwarded-For": "5.5.5.5"},
        meta={"REMOTE_ADDR": "172.18.0.3"},
    )
    assert RateLimitMiddleware._client_ip(req) == "172.18.0.3"
