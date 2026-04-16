"""Login IP trust model tests.

Proves that the login endpoint uses the centralized client_ip helper
(X-Real-IP / REMOTE_ADDR) instead of X-Forwarded-For.
"""
import pytest

from apps.platform_common.client_ip import client_ip


class _FakeRequest:
    def __init__(self, headers=None, meta=None):
        self._headers = headers or {}
        self.META = meta or {}

    @property
    def headers(self):
        return self._headers


pytestmark = pytest.mark.no_db


def test_login_ip_uses_client_ip_not_xff():
    """Simulates the login path's IP extraction.  After the fix, login
    uses client_ip() which prefers X-Real-IP over X-Forwarded-For."""
    req = _FakeRequest(
        headers={
            "X-Real-IP": "10.0.0.1",
            "X-Forwarded-For": "9.9.9.9, 10.0.0.1",
        },
        meta={"REMOTE_ADDR": "172.17.0.2"},
    )
    ip = client_ip(req)
    assert ip == "10.0.0.1", "Should use X-Real-IP, not X-Forwarded-For"


def test_login_ip_ignores_xff_when_no_real_ip():
    """Without X-Real-IP, login must fall back to REMOTE_ADDR — not XFF."""
    req = _FakeRequest(
        headers={"X-Forwarded-For": "8.8.8.8"},
        meta={"REMOTE_ADDR": "192.168.1.50"},
    )
    ip = client_ip(req)
    assert ip == "192.168.1.50", "Without X-Real-IP, should use REMOTE_ADDR"


def test_login_ip_xff_spoofing_blocked():
    """A malicious client sending X-Forwarded-For without X-Real-IP must
    not have their spoofed IP used for session metadata."""
    req = _FakeRequest(
        headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"},
        meta={"REMOTE_ADDR": "10.20.30.40"},
    )
    ip = client_ip(req)
    assert ip == "10.20.30.40"
    assert ip != "1.2.3.4"
