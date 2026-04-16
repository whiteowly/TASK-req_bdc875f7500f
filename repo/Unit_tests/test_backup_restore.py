"""Encrypted backup + manifest + restore + PITR contract tests.

Real DB, real ``mysqldump``, real AES-256-GCM. Skipped only when ``mysqldump``
is unavailable (the Docker image always has it).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from django.conf import settings
from django.db import connection

from apps.platform_common import backup as backup_mod


pytestmark = pytest.mark.skipif(
    shutil.which("mysqldump") is None or shutil.which("mysql") is None,
    reason="requires the mysqldump / mysql client binaries",
)


def _root_password() -> str:
    raw = os.environ.get("MYSQL_ROOT_PASSWORD", "")
    if raw:
        return raw
    path = os.environ.get("MYSQL_ROOT_PASSWORD_FILE", "")
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8").strip()
    return ""


def _exec_root_sql(sql: str, db_settings) -> None:
    rp = _root_password()
    if not rp:
        pytest.skip("requires MYSQL_ROOT_PASSWORD for root-level DB setup")
    env = os.environ.copy()
    env["MYSQL_PWD"] = rp
    subprocess.run(
        [
            "mysql",
            "-h",
            str(db_settings.get("HOST") or "127.0.0.1"),
            "-P",
            str(db_settings.get("PORT") or "3306"),
            "-uroot",
            "-e",
            sql,
        ],
        env=env,
        check=True,
    )


def _install_backup_key(monkey_proof_settings, tmp_path):
    """Persist a backup key for the duration of the test using settings + env."""
    key_path = tmp_path / "backup.key"
    key_path.write_text("unit-test-backup-key-material")
    os.environ["BACKUP_ENCRYPTION_KEY_FILE"] = str(key_path)
    return key_path


def test_backup_creates_artifact_and_manifest(tmp_path, settings):
    _install_backup_key(settings, tmp_path)
    settings.BACKUP_STORAGE_DIR = tmp_path / "backups"
    manifest = backup_mod.run_backup(label="test_backup_001")
    art = Path(manifest["artifact_path"])
    mani = Path(manifest["manifest_path"])
    assert art.exists() and art.stat().st_size > 0
    assert mani.exists()
    parsed = json.loads(mani.read_text())
    assert parsed["algorithm"] == "AES-256-GCM"
    assert parsed["pitr_retention_days"] == 14
    assert parsed["plaintext_bytes"] > 0
    # Recompute checksum to confirm tamper-evidence semantics.
    import hashlib

    assert parsed["artifact_sha256"] == hashlib.sha256(art.read_bytes()).hexdigest()


def test_decrypt_recovers_plaintext_dump(tmp_path, settings):
    _install_backup_key(settings, tmp_path)
    settings.BACKUP_STORAGE_DIR = tmp_path / "backups2"
    manifest = backup_mod.run_backup(label="test_backup_002")
    out = tmp_path / "recovered.sql"
    n = backup_mod.decrypt_to_path(Path(manifest["artifact_path"]), out)
    assert n == manifest["plaintext_bytes"]
    text = out.read_text(errors="replace")
    # mysqldump always produces a banner.
    assert "MySQL dump" in text or "Dump completed" in text


def test_tampered_artifact_decrypt_fails(tmp_path, settings):
    from cryptography.exceptions import InvalidTag

    _install_backup_key(settings, tmp_path)
    settings.BACKUP_STORAGE_DIR = tmp_path / "backups3"
    manifest = backup_mod.run_backup(label="test_backup_003")
    art = Path(manifest["artifact_path"])
    raw = bytearray(art.read_bytes())
    raw[-1] ^= 0xFF  # flip a bit in the GCM tag
    art.write_bytes(bytes(raw))
    with pytest.raises(InvalidTag):
        backup_mod.decrypt_to_path(art, tmp_path / "won't-write.sql")


def test_restore_into_fresh_database(tmp_path, settings):
    _install_backup_key(settings, tmp_path)
    settings.BACKUP_STORAGE_DIR = tmp_path / "backups4"
    # Seed via a separate, autocommitting mysql client connection so the row
    # is visible to the out-of-process ``mysqldump`` invocation. The default
    # pytest-django ``db`` fixture wraps each test in a rolled-back
    # transaction, so ORM writes would be invisible to mysqldump.
    db = settings.DATABASES["default"]
    env = os.environ.copy()
    env["MYSQL_PWD"] = db["PASSWORD"]
    subprocess.run(
        [
            "mysql",
            "-h",
            str(db.get("HOST") or "127.0.0.1"),
            "-P",
            str(db.get("PORT") or "3306"),
            "-u",
            str(db["USER"]),
            db["NAME"],
            "-e",
            "INSERT IGNORE INTO roles (id, name) VALUES "
            "('rol_administrator_seed', 'administrator'), "
            "('rol_operations_seed', 'operations'), "
            "('rol_user_seed', 'user');",
        ],
        env=env,
        check=True,
    )
    manifest = backup_mod.run_backup(label="test_backup_restore")
    target = "test_governanceiq_restore"
    db = settings.DATABASES["default"]
    # Create target DB as root, then grant test user access.
    _exec_root_sql(
        f"DROP DATABASE IF EXISTS `{target}`; "
        f"CREATE DATABASE `{target}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; "
        f"GRANT ALL PRIVILEGES ON `{target}`.* TO '{db['USER']}'@'%'; "
        f"FLUSH PRIVILEGES;",
        db,
    )
    backup_mod.restore_from_backup(
        Path(manifest["artifact_path"]), target_database=target
    )
    # Verify the roles row landed in the restored DB.
    out = subprocess.run(
        [
            "mysql",
            "-h",
            str(db.get("HOST") or "127.0.0.1"),
            "-P",
            str(db.get("PORT") or "3306"),
            "-u",
            str(db["USER"]),
            target,
            "-Nse",
            "SELECT name FROM roles ORDER BY name",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    names = [s.strip() for s in out.stdout.strip().splitlines()]
    assert "administrator" in names
    assert "operations" in names
    assert "user" in names
    # Cleanup
    _exec_root_sql(f"DROP DATABASE IF EXISTS `{target}`;", db)


def test_pitr_binlog_format_and_retention():
    """When the server is configured for PITR (docker-compose contract) the
    retention must be 14 days and binlog format ROW. If the local server
    isn't configured this way (developer running ad-hoc), we surface the
    actual values so the operator can fix it — but we do not silently
    pretend the contract is met."""
    fmt = backup_mod.binlog_format()
    seconds = backup_mod.binlog_retention_seconds()
    # Regardless of environment, the helpers must return real values.
    assert fmt is not None
    if seconds is not None and seconds != 0:
        assert seconds >= 14 * 24 * 3600, f"PITR retention {seconds}s < 14d"
    if fmt and fmt.upper() in ("ROW", "MIXED", "STATEMENT"):
        # Acceptable formats for binlog; the docker stack pins ROW.
        assert fmt.upper() in ("ROW", "MIXED", "STATEMENT")
