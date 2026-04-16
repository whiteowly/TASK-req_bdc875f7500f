"""Self-signed TLS certificate generation for local-dev offline TLS termination.

The proxy container reads the cert/key files at startup. In production these
files MUST be replaced by certificate material from the deployment platform's
secret/cert-management path; the helper here exists so that
``docker compose up --build`` produces a real TLS-serving stack on a fresh
host with no external dependencies.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def generate_self_signed(common_name: str = "governanceiq.local",
                         valid_days: int = 365) -> Tuple[bytes, bytes]:
    """Return ``(cert_pem, key_pem)`` for a fresh self-signed RSA-2048 cert."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "GovernanceIQ Local"),
    ])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=valid_days))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(common_name),
                x509.DNSName("localhost"),
                x509.DNSName("proxy"),
                x509.DNSName("api"),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(private_key=key, algorithm=hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def ensure_files(cert_path: str, key_path: str,
                 *, common_name: str = "governanceiq.local") -> bool:
    """Write self-signed cert/key to the given paths if either is missing.

    Returns ``True`` if new files were written, ``False`` if both already
    exist and were left in place.
    """
    cp = Path(cert_path)
    kp = Path(key_path)
    if cp.exists() and cp.stat().st_size > 0 and kp.exists() and kp.stat().st_size > 0:
        return False
    cp.parent.mkdir(parents=True, exist_ok=True)
    kp.parent.mkdir(parents=True, exist_ok=True)
    cert_pem, key_pem = generate_self_signed(common_name)
    cp.write_bytes(cert_pem)
    kp.write_bytes(key_pem)
    os.chmod(cp, 0o644)
    os.chmod(kp, 0o600)
    return True
