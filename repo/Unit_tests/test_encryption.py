"""AES-256-GCM helpers — encrypts/decrypts roundtrip and tampers fail."""
import pytest
from cryptography.exceptions import InvalidTag

from apps.platform_common.encryption import decrypt, encrypt

pytestmark = pytest.mark.no_db


def test_roundtrip_ok():
    token = encrypt("super-sensitive-pii")
    assert token.startswith("v1.")
    assert "super-sensitive-pii" not in token  # not in plaintext form
    assert decrypt(token) == "super-sensitive-pii"


def test_two_encryptions_produce_different_ciphertext():
    a = encrypt("same input")
    b = encrypt("same input")
    assert a != b  # IV makes it non-deterministic


def test_tampered_ciphertext_fails():
    token = encrypt("payload")
    parts = token.split(".")
    parts[-1] = parts[-1][:-2] + "AB"  # flip last bytes
    tampered = ".".join(parts)
    with pytest.raises(InvalidTag):
        decrypt(tampered)
