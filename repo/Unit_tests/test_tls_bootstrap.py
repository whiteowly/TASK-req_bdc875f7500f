"""TLS bootstrap produces a real X.509 cert + RSA key.

Goes further than file-existence checks: parses the PEM, validates the
issuer/subject, key strength, and exercises an actual TLS handshake using
Python's ``ssl`` module against a tiny in-process server.
"""
from __future__ import annotations

import http.client
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.platform_common.tls import ensure_files, generate_self_signed

pytestmark = pytest.mark.no_db


def test_generate_self_signed_yields_real_x509(tmp_path):
    cert_pem, key_pem = generate_self_signed("test.local", valid_days=2)
    cert = x509.load_pem_x509_certificate(cert_pem)
    assert cert.subject.rfc4514_string().startswith("CN=test.local") or "CN=test.local" in cert.subject.rfc4514_string()
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "test.local" in [d.value for d in san]
    pub = cert.public_key()
    assert isinstance(pub, rsa.RSAPublicKey)
    assert pub.key_size >= 2048


def test_generated_cert_includes_api_san():
    """The self-signed cert must include 'api' as a SAN so the nginx→api
    internal TLS hop can verify the upstream certificate by hostname."""
    cert_pem, _ = generate_self_signed()
    cert = x509.load_pem_x509_certificate(cert_pem)
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    dns_names = [d.value for d in san]
    assert "api" in dns_names, f"'api' SAN missing; found: {dns_names}"
    # Also verify the other expected SANs still present
    assert "governanceiq.local" in dns_names
    assert "localhost" in dns_names
    assert "proxy" in dns_names


def test_ensure_files_idempotent(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    assert ensure_files(str(cert), str(key)) is True
    first_cert_bytes = cert.read_bytes()
    # Second call should leave existing files alone.
    assert ensure_files(str(cert), str(key)) is False
    assert cert.read_bytes() == first_cert_bytes


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"hello-tls")

    def log_message(self, *args, **kwargs):  # silence stderr
        pass


def test_real_tls_handshake_with_generated_cert(tmp_path):
    cert = tmp_path / "tls_cert.pem"
    key = tmp_path / "tls_key.pem"
    ensure_files(str(cert), str(key))

    ctx_server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx_server.load_cert_chain(str(cert), str(key))

    httpd = HTTPServer(("127.0.0.1", 0), _OkHandler)
    httpd.socket = ctx_server.wrap_socket(httpd.socket, server_side=True)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        ctx_client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx_client.load_verify_locations(str(cert))
        ctx_client.check_hostname = False  # self-signed for "governanceiq.local"
        conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx_client, timeout=5)
        conn.connect()
        # Capture the negotiated TLS version before the request — http.client
        # closes the underlying socket as soon as the response body is read.
        negotiated = conn.sock.version()
        assert negotiated in ("TLSv1.2", "TLSv1.3"), negotiated
        conn.request("GET", "/healthz")
        res = conn.getresponse()
        body = res.read()
        assert res.status == 200
        assert body == b"hello-tls"
    finally:
        httpd.shutdown()
        httpd.server_close()
