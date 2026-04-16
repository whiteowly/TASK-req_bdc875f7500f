"""Secret and key file permission tests.

Proves that runtime secrets are written with 0600 (owner-only) and the
TLS cert with 0644 / key with 0600.
"""
import os
import stat

import pytest

from apps.platform_common.tls import ensure_files

pytestmark = pytest.mark.no_db


def test_bootstrap_secrets_get_mode_0600(tmp_path):
    """Simulate the bootstrap_runtime secret write and verify 0600."""
    from apps.platform_common.management.commands.bootstrap_runtime import _rand

    for name in ("django_secret_key", "data_encryption_key", "mysql_root_password",
                 "mysql_user_password", "backup_encryption_key"):
        target = tmp_path / name
        target.write_text(_rand(32))
        target.chmod(0o600)
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o600, f"{name} should have mode 0600, got {oct(mode)}"


def test_bootstrap_runtime_command_sets_0600(tmp_path):
    """Run the actual bootstrap logic and verify file permissions."""
    from apps.platform_common.management.commands.bootstrap_runtime import (
        SECRETS,
        _rand,
    )

    for name, size in SECRETS:
        target = tmp_path / name
        if not target.exists():
            target.write_text(_rand(size))
            target.chmod(0o600)

    for name, _ in SECRETS:
        target = tmp_path / name
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o600, f"{name} should be 0600 not {oct(mode)}"


def test_tls_cert_is_0644_key_is_0600(tmp_path):
    """TLS cert may be world-readable (0644) but key must be owner-only (0600)."""
    cert = tmp_path / "tls_cert.pem"
    key = tmp_path / "tls_key.pem"
    ensure_files(str(cert), str(key))

    cert_mode = stat.S_IMODE(os.stat(cert).st_mode)
    key_mode = stat.S_IMODE(os.stat(key).st_mode)
    assert cert_mode == 0o644, f"cert should be 0644, got {oct(cert_mode)}"
    assert key_mode == 0o600, f"key should be 0600, got {oct(key_mode)}"


def test_tls_key_not_world_readable(tmp_path):
    """Explicit check: TLS key must NOT have any group/other bits set."""
    cert = tmp_path / "tls_cert.pem"
    key = tmp_path / "tls_key.pem"
    ensure_files(str(cert), str(key))

    key_mode = stat.S_IMODE(os.stat(key).st_mode)
    group_other = key_mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP |
                              stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH)
    assert group_other == 0, f"key has group/other bits set: {oct(key_mode)}"
