"""Static consistency check: README must not contain the deprecated
'api speaks plain HTTP' statement that contradicts the TLS-on-all-hops
architecture.
"""
import pytest
from pathlib import Path

pytestmark = pytest.mark.no_db

README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_does_not_claim_api_speaks_plain_http():
    """The old statement 'api container itself speaks plain HTTP' was
    removed when gunicorn was configured with --certfile/--keyfile.
    Ensure it has not been re-introduced."""
    text = README.read_text()
    assert "api container itself speaks plain HTTP" not in text, (
        "README still contains the deprecated plain-HTTP statement"
    )


def test_readme_documents_tls_on_all_hops():
    """README must contain the authoritative TLS-on-all-hops statement."""
    text = README.read_text()
    assert "TLS on all network hops" in text, (
        "README is missing the 'TLS on all network hops' documentation"
    )


def test_readme_no_plaintext_proxy_to_api():
    """README must not say the proxy->api hop is plaintext."""
    text = README.read_text()
    # The old phrasing variants that should not appear
    for phrase in [
        "plain HTTP only on the trusted",
        "speaks plain HTTP only on",
        "proxy_pass http://gov_api",
    ]:
        assert phrase not in text, (
            f"README still contains deprecated plaintext reference: '{phrase}'"
        )
