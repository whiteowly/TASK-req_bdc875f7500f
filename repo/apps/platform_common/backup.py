"""Encrypted backup, restore, and PITR helpers backed by MySQL tooling.

These functions are real:

- ``run_backup`` shells out to ``mysqldump`` against the configured database
  and writes an AES-256-GCM-encrypted artifact (plus a JSON manifest with
  the SHA-256 checksum) under ``BACKUP_STORAGE_DIR``.
- ``decrypt_to_path`` recovers a plaintext SQL dump from a backup artifact.
- ``restore_from_backup`` shells out to the ``mysql`` client to apply that
  dump back into a target database.
- ``list_binlogs`` and ``binlog_retention_seconds`` interrogate the live
  MySQL server to confirm the PITR retention contract (14 days).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.db import connection


PITR_RETENTION_DAYS = 14


def _backup_key() -> bytes:
    raw = os.environ.get("BACKUP_ENCRYPTION_KEY", "")
    if not raw:
        path = os.environ.get("BACKUP_ENCRYPTION_KEY_FILE", "")
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read().strip()
    if not raw:
        raise RuntimeError("BACKUP_ENCRYPTION_KEY is not configured")
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _mysql_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["MYSQL_PWD"] = settings.DATABASES["default"]["PASSWORD"]
    return env


def _mysql_args() -> List[str]:
    db = settings.DATABASES["default"]
    return [
        "-h",
        str(db.get("HOST") or "127.0.0.1"),
        "-P",
        str(db.get("PORT") or "3306"),
        "-u",
        str(db["USER"]),
    ]


def run_backup(
    *, label: Optional[str] = None, output_dir: Optional[Path] = None
) -> Dict[str, str]:
    """Produce an encrypted backup of the configured MySQL database.

    Writes ``<output_dir>/<label>.sql.enc`` and a sibling JSON manifest. The
    manifest records the algorithm, key id, ciphertext checksum, plaintext
    checksum, plaintext byte length, server time, and source DB name.
    Returns the manifest as a dict.
    """
    out = Path(output_dir) if output_dir else Path(settings.BACKUP_STORAGE_DIR)
    out.mkdir(parents=True, exist_ok=True)
    label = label or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    db = settings.DATABASES["default"]

    dump_proc = subprocess.run(
        [
            "mysqldump",
            *_mysql_args(),
            "--single-transaction",
            "--quick",
            "--routines",
            "--triggers",
            "--no-tablespaces",
            "--default-character-set=utf8mb4",
            # GTIDs are a server-global identifier set, not per-database. We
            # strip the SET @@GLOBAL.GTID_PURGED preamble so the dump is
            # restorable into ANY database name on the same server (PITR
            # side-by-side recovery, smoke tests, etc.). The full GTID
            # state still lives in the live binlog.
            "--set-gtid-purged=OFF",
            db["NAME"],
        ],
        env=_mysql_env(),
        capture_output=True,
        check=True,
    )
    plaintext = dump_proc.stdout
    if not plaintext:
        raise RuntimeError("mysqldump produced empty output")

    key = _backup_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
    artifact_path = out / f"{label}.sql.enc"
    with artifact_path.open("wb") as fh:
        fh.write(b"GIQBKP1\n")  # magic header
        fh.write(nonce)
        fh.write(ct)

    manifest = {
        "label": label,
        "algorithm": "AES-256-GCM",
        "key_id": settings.DATA_ENCRYPTION_KEY_ID,
        "artifact_path": str(artifact_path),
        "artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
        "plaintext_bytes": len(plaintext),
        "database": db["NAME"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pitr_retention_days": PITR_RETENTION_DAYS,
    }
    manifest_path = out / f"{label}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def decrypt_to_path(artifact_path: Path, dest_path: Path) -> int:
    """Decrypt a ``.sql.enc`` artifact produced by :func:`run_backup`.

    Returns the number of plaintext bytes written.
    """
    raw = Path(artifact_path).read_bytes()
    if not raw.startswith(b"GIQBKP1\n"):
        raise ValueError("not a recognized GovernanceIQ backup artifact")
    body = raw[len(b"GIQBKP1\n") :]
    nonce, ct = body[:12], body[12:]
    pt = AESGCM(_backup_key()).decrypt(nonce, ct, associated_data=None)
    Path(dest_path).write_bytes(pt)
    return len(pt)


def restore_from_backup(artifact_path: Path, *, target_database: str) -> None:
    """Apply an encrypted backup into ``target_database`` (must already exist)."""
    with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        decrypt_to_path(Path(artifact_path), tmp_path)
        with tmp_path.open("rb") as fh:
            subprocess.run(
                ["mysql", *_mysql_args(), target_database],
                env=_mysql_env(),
                stdin=fh,
                check=True,
            )
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:  # pragma: no cover
            pass


def binlog_retention_seconds() -> Optional[int]:
    """Read the configured ``binlog_expire_logs_seconds`` from the live server."""
    with connection.cursor() as cur:
        cur.execute("SHOW VARIABLES LIKE 'binlog_expire_logs_seconds'")
        row = cur.fetchone()
    if not row:
        return None
    return int(row[1])


def binlog_format() -> Optional[str]:
    with connection.cursor() as cur:
        cur.execute("SHOW VARIABLES LIKE 'binlog_format'")
        row = cur.fetchone()
    return row[1] if row else None


def list_binlogs() -> List[Tuple[str, int]]:
    """Return ``[(name, size_bytes), ...]`` for the server's binary logs.

    Returns an empty list when binary logging is disabled. Any other
    OperationalError (privilege missing, server unreachable) is propagated
    so the caller can react instead of silently planning a 0-byte PITR.
    """
    from django.db import OperationalError

    with connection.cursor() as cur:
        try:
            cur.execute("SHOW BINARY LOGS")
        except OperationalError as exc:
            # ER_NO_BINARY_LOGGING (1381) — server has no binary logging.
            if "1381" in str(exc) or "binary logging" in str(exc).lower():
                return []
            raise
        return [(row[0], int(row[1])) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Point-in-time recovery
# ---------------------------------------------------------------------------


def list_backup_manifests(directory: Optional[Path] = None) -> List[Dict]:
    """Return manifests sorted by ``created_at`` ascending."""
    d = Path(directory) if directory else Path(settings.BACKUP_STORAGE_DIR)
    if not d.exists():
        return []
    out = []
    for path in sorted(d.glob("*.manifest.json")):
        try:
            m = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        m["_manifest_path"] = str(path)
        out.append(m)
    out.sort(key=lambda m: m.get("created_at", ""))
    return out


def select_base_backup(manifests: List[Dict], target_time: datetime) -> Optional[Dict]:
    """Pick the most recent backup whose ``created_at <= target_time``."""
    best = None
    for m in manifests:
        try:
            ts = datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ts <= target_time and (best is None or ts > best[0]):
            best = (ts, m)
    return best[1] if best else None


def plan_pitr(target_time: datetime, backup_dir: Optional[Path] = None) -> Dict:
    """Compute the PITR plan: which backup to restore and which binlog
    range to apply."""
    from datetime import timedelta as _td

    target_time = (
        target_time.astimezone(timezone.utc)
        if target_time.tzinfo
        else target_time.replace(tzinfo=timezone.utc)
    )
    cutoff_min = datetime.now(timezone.utc) - _td(days=PITR_RETENTION_DAYS)
    if target_time < cutoff_min:
        raise ValueError(
            f"target_time {target_time.isoformat()} is older than the "
            f"{PITR_RETENTION_DAYS}-day PITR window"
        )
    manifests = list_backup_manifests(backup_dir)
    base = select_base_backup(manifests, target_time)
    if base is None:
        raise FileNotFoundError(
            f"no backup at or before {target_time.isoformat()} in "
            f"{backup_dir or settings.BACKUP_STORAGE_DIR}"
        )
    binlogs = [name for name, _ in list_binlogs()]
    base_time = datetime.fromisoformat(base["created_at"].replace("Z", "+00:00"))
    return {
        "target_time": target_time.isoformat(),
        "base_backup": base["artifact_path"],
        "base_backup_label": base["label"],
        "base_backup_created_at": base["created_at"],
        "binlogs": binlogs,
        # mysqlbinlog --start/stop-datetime expect server-local naive datetimes;
        # we convert to UTC and emit naive ISO so the contract is unambiguous.
        "start_datetime": base_time.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "stop_datetime": target_time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _root_password() -> str:
    raw = os.environ.get("MYSQL_ROOT_PASSWORD", "")
    if not raw:
        path = os.environ.get("MYSQL_ROOT_PASSWORD_FILE", "")
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read().strip()
    return raw


def apply_binlogs_via_remote_stream(
    *,
    source_database: str,
    target_database: str,
    plan: Dict,
    root_password: Optional[str] = None,
) -> int:
    """Stream binlogs from the live server with ``mysqlbinlog
    --read-from-remote-server`` and apply the events that originated from
    ``source_database`` into ``target_database``.

    When ``source_database`` differs from ``target_database`` we use
    ``--rewrite-db=source->target`` so binlog events that targeted the
    source database land in the target one — required when running PITR
    into a side-by-side recovery database on the same MySQL server.
    """
    db = settings.DATABASES["default"]
    rp = root_password or _root_password()
    if not rp:
        raise RuntimeError("MYSQL_ROOT_PASSWORD is required for PITR binlog replay")
    binlogs = plan["binlogs"]
    if not binlogs:
        return 0
    # SSL must be skipped for the local-dev offline docker-compose stack
    # because the MySQL server's auto-generated TLS material is self-signed.
    # The exact flag differs between Oracle's mysqlbinlog (``--ssl-mode=DISABLED``)
    # and MariaDB's (``--skip-ssl``). Detect at runtime.
    help_text = subprocess.run(
        ["mysqlbinlog", "--help"],
        capture_output=True,
        text=True,
    ).stdout
    ssl_flag = "--ssl-mode=DISABLED" if "--ssl-mode" in help_text else "--skip-ssl"
    cmd_stream = [
        "mysqlbinlog",
        "--read-from-remote-server",
        f"--host={db.get('HOST') or '127.0.0.1'}",
        f"--port={db.get('PORT') or '3306'}",
        "--user=root",
        f"--password={rp}",
        ssl_flag,
        "--start-datetime=" + plan["start_datetime"],
        "--stop-datetime=" + plan["stop_datetime"],
        # ``--skip-gtids`` strips GTID metadata from the replayed events so
        # they execute as fresh transactions on the target server. This is
        # required for in-place PITR into a side-by-side recovery database
        # because the binlog GTIDs are already in @@GTID_EXECUTED on the
        # same server and would otherwise be silently no-op'd.
        "--skip-gtids",
    ]
    if source_database != target_database:
        # ``--rewrite-db`` remaps the database name in Table_map events.
        # When in use, the post-rewrite name is what mysqlbinlog's
        # ``--database`` filter inspects, so we filter on the target name.
        cmd_stream.append(f"--rewrite-db={source_database}->{target_database}")
        cmd_stream.append("--database=" + target_database)
    else:
        cmd_stream.append("--database=" + source_database)
    cmd_stream.extend(binlogs)
    # Stream into a temp file so we can both count the binlog bytes that
    # came out of mysqlbinlog AND apply them; piping through ``mysql`` would
    # hide the upstream byte count.
    with tempfile.NamedTemporaryFile(suffix=".binlog.sql", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with tmp_path.open("wb") as out_fh:
            binlog_proc = subprocess.Popen(
                cmd_stream,
                stdout=out_fh,
                stderr=subprocess.PIPE,
            )
            _, err_binlog = binlog_proc.communicate()
        if binlog_proc.returncode != 0:
            raise RuntimeError(
                f"PITR binlog stream failed rc={binlog_proc.returncode} "
                f"stderr={err_binlog!r}"
            )
        bytes_streamed = tmp_path.stat().st_size
        # The binlog stream contains ``SET @@SESSION.PSEUDO_SLAVE_MODE``
        # and other privileged statements that require SUPER or
        # REPLICATION_APPLIER. Use root for the apply step.
        db2 = settings.DATABASES["default"]
        apply_args = [
            "mysql",
            "-h",
            str(db2.get("HOST") or "127.0.0.1"),
            "-P",
            str(db2.get("PORT") or "3306"),
            "-uroot",
            target_database,
        ]
        apply_env = os.environ.copy()
        apply_env["MYSQL_PWD"] = rp
        with tmp_path.open("rb") as in_fh:
            apply_proc = subprocess.run(
                apply_args,
                stdin=in_fh,
                env=apply_env,
                capture_output=True,
            )
        if apply_proc.returncode != 0:
            raise RuntimeError(
                f"PITR binlog apply failed rc={apply_proc.returncode} "
                f"stderr={apply_proc.stderr!r}"
            )
        return bytes_streamed
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:  # pragma: no cover
            pass


def run_pitr(
    *,
    target_time: datetime,
    target_database: str,
    source_database: Optional[str] = None,
    backup_dir: Optional[Path] = None,
    root_password: Optional[str] = None,
    dry_run: bool = False,
) -> Dict:
    """Full PITR: restore the base backup at or before ``target_time`` into
    ``target_database`` and replay binlogs originating in
    ``source_database`` (defaults to the manifest's ``database``) up to
    ``target_time``."""
    plan = plan_pitr(target_time, backup_dir=backup_dir)
    src = source_database
    if src is None:
        # Recover the source DB name from the chosen manifest so the binlog
        # filter is correct even if Django's settings point elsewhere.
        manifests = list_backup_manifests(backup_dir)
        for m in manifests:
            if m["label"] == plan["base_backup_label"]:
                src = m.get("database")
                break
        if src is None:
            src = settings.DATABASES["default"]["NAME"]
    plan["source_database"] = src
    plan["target_database"] = target_database
    if dry_run:
        plan["dry_run"] = True
        return plan
    restore_from_backup(Path(plan["base_backup"]), target_database=target_database)
    plan["binlog_bytes_applied"] = apply_binlogs_via_remote_stream(
        source_database=src,
        target_database=target_database,
        plan=plan,
        root_password=root_password,
    )
    plan["dry_run"] = False
    return plan
