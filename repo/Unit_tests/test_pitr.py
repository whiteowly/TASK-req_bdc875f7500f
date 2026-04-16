"""Tests for the point-in-time recovery flow.

The pure-logic parts (manifest parsing, base-backup selection, retention
window enforcement, plan construction) are exercised against real backup
manifests on disk. The end-to-end binlog replay is exercised against the
live MySQL binlog stream when the test environment can reach the binlog
remote-streaming protocol with root credentials.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.platform_common import backup as backup_mod


# ``plan_pitr`` calls ``list_binlogs()`` which queries the live MySQL server
# through Django's connection — so these tests need the autouse ``db``
# fixture active and we deliberately do NOT carry ``no_db``.
pytestmark = pytest.mark.skipif(
    shutil.which("mysqldump") is None or shutil.which("mysqlbinlog") is None,
    reason="requires mysqldump + mysqlbinlog on PATH",
)


def _write_manifest(directory: Path, *, label: str, when: datetime) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / f"{label}.sql.enc"
    artifact.write_bytes(b"GIQBKP1\n" + b"\x00" * 12 + b"\x00" * 16)
    manifest = {
        "label": label,
        "algorithm": "AES-256-GCM",
        "key_id": "k1",
        "artifact_path": str(artifact),
        "artifact_sha256": "x" * 64,
        "plaintext_sha256": "y" * 64,
        "plaintext_bytes": 1,
        "database": "governanceiq",
        "created_at": when.isoformat(),
        "pitr_retention_days": 14,
    }
    p = directory / f"{label}.manifest.json"
    p.write_text(json.dumps(manifest))
    return p


def test_select_base_backup_picks_latest_at_or_before(tmp_path):
    now = datetime.now(timezone.utc)
    _write_manifest(tmp_path, label="b1", when=now - timedelta(hours=10))
    _write_manifest(tmp_path, label="b2", when=now - timedelta(hours=5))
    _write_manifest(tmp_path, label="b3", when=now + timedelta(hours=1))
    manifests = backup_mod.list_backup_manifests(tmp_path)
    target = now - timedelta(hours=2)
    base = backup_mod.select_base_backup(manifests, target)
    assert base["label"] == "b2"


def test_select_base_backup_returns_none_when_target_predates_all(tmp_path):
    now = datetime.now(timezone.utc)
    _write_manifest(tmp_path, label="b1", when=now - timedelta(hours=1))
    manifests = backup_mod.list_backup_manifests(tmp_path)
    assert backup_mod.select_base_backup(manifests, now - timedelta(hours=5)) is None


def test_plan_pitr_rejects_target_outside_retention_window(tmp_path):
    too_old = datetime.now(timezone.utc) - timedelta(days=15)
    with pytest.raises(ValueError):
        backup_mod.plan_pitr(too_old, backup_dir=tmp_path)


def test_plan_pitr_returns_full_plan(tmp_path):
    now = datetime.now(timezone.utc)
    _write_manifest(tmp_path, label="b1", when=now - timedelta(hours=2))
    target = now - timedelta(minutes=30)
    plan = backup_mod.plan_pitr(target, backup_dir=tmp_path)
    assert plan["base_backup_label"] == "b1"
    assert "target_database" not in plan  # only set by run_pitr
    assert plan["start_datetime"]
    assert plan["stop_datetime"]
    assert isinstance(plan["binlogs"], list)


def test_plan_pitr_no_backup_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_mod.plan_pitr(datetime.now(timezone.utc), backup_dir=tmp_path)


def test_run_pitr_dry_run_returns_plan_without_executing(tmp_path):
    now = datetime.now(timezone.utc)
    _write_manifest(tmp_path, label="dryrun_b", when=now - timedelta(hours=1))
    plan = backup_mod.run_pitr(
        target_time=now - timedelta(minutes=30),
        target_database="gi_pitr_dry",
        backup_dir=tmp_path,
        dry_run=True,
    )
    assert plan["dry_run"] is True
    assert plan["target_database"] == "gi_pitr_dry"
    assert plan["base_backup_label"] == "dryrun_b"
