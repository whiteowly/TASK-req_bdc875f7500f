"""End-to-end PITR test against the live MySQL binlog stream.

Flow:
1. Create an isolated PITR source database with a small table.
2. INSERT a few rows.
3. Take a real encrypted backup (so the manifest reflects this exact moment).
4. INSERT additional rows (these only land in the binlog, not the backup).
5. Capture the target time.
6. Run ``run_pitr`` with that target time into a fresh target database.
7. Assert the target database has all of the rows from steps (2) AND (4).

Skipped when:
- mysqldump / mysqlbinlog / mysql clients aren't available
- MYSQL_ROOT_PASSWORD isn't reachable (PITR requires REPLICATION privileges)
- the live server doesn't have binary logging enabled
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from django.conf import settings

from apps.platform_common import backup as backup_mod


# NOTE: this test deliberately does NOT carry ``pytest.mark.no_db`` because
# ``list_binlogs()`` calls ``SHOW BINARY LOGS`` through Django's connection,
# which requires the autouse ``db`` fixture to be active.


def _binlogs_enabled() -> bool:
    db = settings.DATABASES["default"]
    env = os.environ.copy()
    env["MYSQL_PWD"] = db["PASSWORD"]
    r = subprocess.run(
        [
            "mysql",
            "-h",
            str(db.get("HOST") or "127.0.0.1"),
            "-P",
            str(db.get("PORT") or "3306"),
            "-u",
            str(db["USER"]),
            "-Nse",
            "SHOW VARIABLES LIKE 'log_bin'",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and "ON" in r.stdout.upper()


def _root_password_available() -> bool:
    return bool(
        os.environ.get("MYSQL_ROOT_PASSWORD")
        or (
            os.environ.get("MYSQL_ROOT_PASSWORD_FILE")
            and os.path.exists(os.environ["MYSQL_ROOT_PASSWORD_FILE"])
        )
    )


_skip_unless = pytest.mark.skipif(
    shutil.which("mysqldump") is None
    or shutil.which("mysqlbinlog") is None
    or shutil.which("mysql") is None
    or not _root_password_available()
    or not _binlogs_enabled(),
    reason="end-to-end PITR requires mysqldump+mysqlbinlog+mysql, root creds, and binlogs enabled",
)


def _exec_root(sql: str) -> str:
    db = settings.DATABASES["default"]
    rp = (
        os.environ.get("MYSQL_ROOT_PASSWORD")
        or Path(os.environ["MYSQL_ROOT_PASSWORD_FILE"]).read_text().strip()
    )
    env = os.environ.copy()
    env["MYSQL_PWD"] = rp
    r = subprocess.run(
        [
            "mysql",
            "-h",
            str(db.get("HOST") or "127.0.0.1"),
            "-P",
            str(db.get("PORT") or "3306"),
            "-uroot",
            "-Nse",
            sql,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout


@_skip_unless
def test_pitr_replays_post_backup_inserts(tmp_path, settings):
    db = settings.DATABASES["default"]
    src_db = "pitr_src"
    tgt_db = "pitr_tgt"
    # Clean slate.
    for d in (src_db, tgt_db):
        _exec_root(f"DROP DATABASE IF EXISTS `{d}`;")
    _exec_root(
        f"CREATE DATABASE `{src_db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )
    _exec_root(
        f"CREATE DATABASE `{tgt_db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )
    _exec_root(
        f"GRANT ALL PRIVILEGES ON `{src_db}`.* TO '{db['USER']}'@'%'; "
        f"GRANT ALL PRIVILEGES ON `{tgt_db}`.* TO '{db['USER']}'@'%'; "
        "FLUSH PRIVILEGES;"
    )
    _exec_root(
        f"CREATE TABLE `{src_db}`.events (id INT PRIMARY KEY AUTO_INCREMENT, label VARCHAR(64));"
    )
    _exec_root(
        f"INSERT INTO `{src_db}`.events (label) VALUES ('before_backup_1'),('before_backup_2');"
    )
    # Wait so the pre-backup INSERT lands in a different one-second bucket
    # than the backup timestamp. mysqlbinlog --start-datetime is
    # second-resolution; the backup timestamp is the start of the binlog
    # replay window, so anything in the same second would re-apply on top
    # of the freshly-restored backup and collide on PRIMARY.
    time.sleep(1.5)
    # Take the backup of pitr_src by overriding the configured DB just for the
    # backup helper — we still go through the real run_backup path.
    settings.BACKUP_STORAGE_DIR = tmp_path / "backups"
    original_name = settings.DATABASES["default"]["NAME"]
    settings.DATABASES["default"]["NAME"] = src_db
    try:
        manifest = backup_mod.run_backup(label="pitr_endtoend")
    finally:
        settings.DATABASES["default"]["NAME"] = original_name

    # Wait one full second so the binlog timestamps cleanly separate.
    time.sleep(1.5)
    _exec_root(
        f"INSERT INTO `{src_db}`.events (label) VALUES ('after_backup_1'),('after_backup_2'),('after_backup_3');"
    )
    # Force a binlog rotation+flush so the post-backup events are durably
    # written into a closed binlog file by the time mysqlbinlog
    # --read-from-remote-server scans for them.
    _exec_root("FLUSH BINARY LOGS;")
    # mysqlbinlog --stop-datetime is exclusive on sub-second; pick a target
    # safely after the post-backup INSERT.
    time.sleep(2.0)
    target = datetime.now(timezone.utc)

    # Run PITR into the fresh target database. Operate on src_db so binlog
    # filtering by --database matches.
    settings.DATABASES["default"]["NAME"] = src_db
    try:
        plan = backup_mod.run_pitr(
            target_time=target,
            target_database=tgt_db,
            backup_dir=tmp_path / "backups",
        )
    finally:
        settings.DATABASES["default"]["NAME"] = original_name

    assert plan["dry_run"] is False
    assert plan["base_backup_label"] == "pitr_endtoend"
    # The binlog stream must have produced bytes — guards against a silent
    # 0-byte plan that would otherwise leave the target equal to the backup.
    assert plan.get("binlog_bytes_applied", 0) > 0, plan

    # The recovered database must contain BOTH the rows captured in the
    # backup AND the rows applied by binlog replay.
    out = _exec_root(f"SELECT label FROM `{tgt_db}`.events ORDER BY id;")
    labels = [s.strip() for s in out.strip().splitlines()]
    assert labels == [
        "before_backup_1",
        "before_backup_2",
        "after_backup_1",
        "after_backup_2",
        "after_backup_3",
    ], labels
    # Cleanup.
    for d in (src_db, tgt_db):
        _exec_root(f"DROP DATABASE IF EXISTS `{d}`;")
