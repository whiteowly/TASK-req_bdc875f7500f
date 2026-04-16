"""Static checks that the nginx TLS proxy config is consistent with the spec."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


def _conf_text() -> str:
    p = Path(__file__).resolve().parent.parent / "docker" / "proxy" / "nginx.conf"
    return p.read_text(encoding="utf-8")


def test_listens_on_443_with_ssl():
    text = _conf_text()
    assert "listen 443 ssl" in text


def test_loads_runtime_secret_cert_paths():
    text = _conf_text()
    assert "/run/runtime-secrets/tls_cert.pem" in text
    assert "/run/runtime-secrets/tls_key.pem" in text


def test_redirects_plain_http_to_https():
    text = _conf_text()
    assert "return 301 https://$host$request_uri" in text


def test_modern_tls_versions_only():
    text = _conf_text()
    assert "TLSv1.2" in text
    assert "TLSv1.3" in text
    assert "SSLv3" not in text
    assert "TLSv1 " not in text  # explicit 1.0
    assert "TLSv1.1" not in text


def test_hsts_header_present():
    text = _conf_text()
    assert "Strict-Transport-Security" in text


def test_proxies_to_api_upstream():
    text = _conf_text()
    assert "server api:8000" in text
    assert "proxy_pass https://gov_api" in text
