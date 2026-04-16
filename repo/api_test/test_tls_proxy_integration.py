"""Live HTTPS round-trip through the nginx proxy.

Requires Docker + the project's docker-compose stack to be reachable. When
Docker isn't available we skip cleanly — but on every machine where Docker
is available (which is the project's documented runtime contract) this test
boots the full stack, performs a real TLS handshake, and validates a 401
envelope from the api through the proxy.

This test does NOT mock anything: the cert is real, the proxy is real,
the api is real, and MySQL is real.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def _compose_cmd() -> list[str] | None:
    if shutil.which("docker") is not None:
        r = subprocess.run(
            ["docker", "compose", "version"], capture_output=True, text=True
        )
        if r.returncode == 0:
            return ["docker", "compose"]
    if shutil.which("docker-compose") is not None:
        return ["docker-compose"]
    return None


def _compose_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME") or REPO_ROOT.name


def _compose_network_name() -> str:
    return f"{_compose_project_name()}_default"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    if _compose_cmd() is None:
        return False
    r = subprocess.run(["docker", "info"], capture_output=True, text=True)
    return r.returncode == 0


pytestmark = [
    pytest.mark.no_db,
    pytest.mark.skipif(
        not _docker_available() or os.environ.get("SKIP_TLS_INTEGRATION") == "1",
        reason="docker not available or SKIP_TLS_INTEGRATION=1",
    ),
]


def _compose(
    *args: str, check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    cmd = _compose_cmd()
    if cmd is None:
        raise RuntimeError("docker compose command is unavailable")
    return subprocess.run(
        [*cmd, *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=capture,
        text=True,
        check=check,
    )


@pytest.fixture(scope="module")
def proxy_stack():
    _compose("down", "-v", check=False)
    _compose("up", "-d", "--wait", "bootstrap", "db")
    _compose("up", "-d", "api", "proxy")
    # Wait until proxy can actually reach the api (a 401 status means
    # nginx → gunicorn → DRF view returned cleanly; a 502 means nginx
    # cannot yet reach the upstream worker).
    network = _compose_network_name()
    deadline = time.time() + 180
    last_out = ""
    while time.time() < deadline:
        r = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                network,
                "curlimages/curl:8.10.1",
                "-sk",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "https://proxy:443/api/v1/audit/logs",
            ],
            capture_output=True,
            text=True,
        )
        last_out = r.stdout + r.stderr
        if last_out.strip() == "401":
            break
        time.sleep(3)
    else:
        _compose("logs", "proxy", check=False)
        _compose("logs", "api", check=False)
        pytest.fail(f"proxy → api did not become ready: {last_out}")
    yield
    _compose("down", "-v", check=False)


def _run_in_proxy_network(cmd: str) -> subprocess.CompletedProcess:
    """Execute ``cmd`` from within the ``proxy`` container so we hit the
    real listening socket without depending on host port forwarding."""
    compose = _compose_cmd() or ["docker", "compose"]
    return subprocess.run(
        [*compose, "exec", "-T", "proxy", "sh", "-c", cmd],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


def _run_curl_via_sidecar(url: str) -> str:
    """Hit ``url`` from a curl sidecar container that joins the compose
    network. Returns ``"<status>\\n<body>"``."""
    network = _compose_network_name()
    r = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "curlimages/curl:8.10.1",
            "-sk",
            "-o",
            "/dev/stdout",
            "-w",
            "\\n%{http_code}",
            url,
        ],
        capture_output=True,
        text=True,
    )
    return r.stdout


def test_https_handshake_returns_401_envelope(proxy_stack):
    out = _run_curl_via_sidecar("https://proxy:443/api/v1/audit/logs")
    body, _, status = out.rpartition("\n")
    assert status.strip() == "401", out
    payload = json.loads(body)
    assert payload["error"]["code"] == "unauthorized"
    assert payload["error"]["request_id"]


def test_plain_http_redirects_to_https(proxy_stack):
    network = _compose_network_name()
    r = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "curlimages/curl:8.10.1",
            "-skI",
            "http://proxy:80/api/v1/audit/logs",
        ],
        capture_output=True,
        text=True,
    )
    out = r.stdout + r.stderr
    assert "301" in out, out
    assert "location: https://" in out.lower(), out


def test_negotiated_tls_version_modern(proxy_stack):
    # openssl ships in nginx:alpine, but not as `openssl` on PATH directly —
    # the s_client helper is available, however. Run it inside the proxy
    # container so we don't have to discover the compose network name.
    compose = _compose_cmd() or ["docker", "compose"]
    r = subprocess.run(
        [
            *compose,
            "exec",
            "-T",
            "proxy",
            "sh",
            "-c",
            "apk add --no-cache openssl >/dev/null 2>&1; "
            "echo | openssl s_client -connect 127.0.0.1:443 -servername governanceiq.local "
            "2>/dev/null | grep -E 'Protocol|Cipher'",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    out = r.stdout + r.stderr
    assert "TLSv1.2" in out or "TLSv1.3" in out, out
