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
import re
import shlex
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
    deadline = time.time() + 180
    last_out = "proxy not ready"
    while time.time() < deadline:
        r = _run_proxy_curl(
            [
                "-sk",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "https://127.0.0.1:443/api/v1/audit/logs",
            ]
        )
        status = _status_from_http_trace(r.stdout)
        last_out = r.stdout + r.stderr
        if status == 401:
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


def _status_from_http_trace(trace: str) -> int | None:
    text = trace.strip()
    if not text or not text.isdigit():
        return None
    return int(text)


def _run_proxy_curl(args: list[str]) -> subprocess.CompletedProcess:
    cmd = "apk add --no-cache curl >/dev/null 2>&1; curl " + " ".join(
        shlex.quote(arg) for arg in args
    )
    r = _run_in_proxy_network(cmd)
    return r


def _https_get_via_proxy_exec(path: str) -> tuple[int | None, str, str]:
    r = _run_proxy_curl(
        [
            "-sk",
            "-o",
            "/dev/stdout",
            "-w",
            "\\n%{http_code}",
            f"https://127.0.0.1:443{path}",
        ]
    )
    body, _, status = r.stdout.rpartition("\n")
    trace = r.stdout + r.stderr
    return _status_from_http_trace(status), body, trace


def test_https_handshake_returns_401_envelope(proxy_stack):
    status, body, trace = _https_get_via_proxy_exec("/api/v1/audit/logs")
    assert status == 401, trace
    payload = json.loads(body)
    assert payload["error"]["code"] == "unauthorized"
    assert payload["error"]["request_id"]


def test_plain_http_redirects_to_https(proxy_stack):
    r = _run_proxy_curl(
        [
            "-skI",
            "http://127.0.0.1:80/api/v1/audit/logs",
        ]
    )
    out = r.stdout + r.stderr
    assert "301" in out, out
    assert "location: https://" in out.lower(), out


def test_negotiated_tls_version_modern(proxy_stack):
    r = _run_proxy_curl(
        [
            "-skv",
            "https://127.0.0.1:443/api/v1/audit/logs",
            "-o",
            "/dev/null",
        ]
    )
    out = r.stdout + r.stderr
    match = re.search(r"(TLSv1\.[23])", out)
    version = match.group(1) if match else ""
    assert version in {"TLSv1.2", "TLSv1.3"}, version
