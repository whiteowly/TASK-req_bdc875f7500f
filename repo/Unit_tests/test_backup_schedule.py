"""Backup schedule state management, env-backed defaults, and tick logic.

Tests exercise:
- First singleton creation seeds cron/timezone from settings env values.
- Subsequent calls preserve operator-edited DB values.
- Scheduling decisions (due/not-due, advancement, idempotency).
- Tick uses stored state values to compute next run.

The actual backup execution path (mysqldump + encryption) is covered by
test_backup_restore.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from django.utils import timezone as dj_tz

from apps.platform_common.cron import next_fire
from apps.platform_common.models import BackupScheduleState
from apps.platform_common.scheduler import tick_backup_schedule


@pytest.fixture
def backup_state(db):
    """Create an active backup schedule state."""
    state = BackupScheduleState.get_or_create_singleton()
    state.cron_expr = "0 1 * * *"
    state.timezone = "UTC"
    state.active = True
    state.next_run_at = dj_tz.now() + timedelta(hours=2)  # not due
    state.save()
    return state


# ---------------------------------------------------------------------------
# Env-backed defaults on first creation
# ---------------------------------------------------------------------------

def test_first_creation_seeds_from_settings(db, settings):
    """First get_or_create_singleton() seeds cron_expr and timezone from
    settings.BACKUP_CRON_EXPR / settings.BACKUP_CRON_TZ."""
    settings.BACKUP_CRON_EXPR = "30 2 * * *"
    settings.BACKUP_CRON_TZ = "America/New_York"

    state = BackupScheduleState.get_or_create_singleton()
    assert state.cron_expr == "30 2 * * *"
    assert state.timezone == "America/New_York"


def test_subsequent_calls_preserve_db_values(db, settings):
    """Once the row exists, get_or_create_singleton() does not overwrite
    operator-customized DB values even if settings differ."""
    settings.BACKUP_CRON_EXPR = "0 4 * * *"
    settings.BACKUP_CRON_TZ = "Europe/London"

    # First call — seeds from settings.
    state = BackupScheduleState.get_or_create_singleton()
    assert state.cron_expr == "0 4 * * *"

    # Operator changes the cron in-DB.
    state.cron_expr = "0 5 * * *"
    state.timezone = "Asia/Tokyo"
    state.save()

    # Change settings to something else.
    settings.BACKUP_CRON_EXPR = "0 6 * * *"
    settings.BACKUP_CRON_TZ = "US/Pacific"

    # Second call — returns existing DB row, not the new settings.
    state2 = BackupScheduleState.get_or_create_singleton()
    assert state2.cron_expr == "0 5 * * *"
    assert state2.timezone == "Asia/Tokyo"


def test_default_settings_applied_when_env_not_set(db, settings):
    """When BACKUP_CRON_EXPR / BACKUP_CRON_TZ are at their defaults, the
    singleton row is created with those defaults."""
    # settings already has BACKUP_CRON_EXPR = "0 1 * * *" and
    # BACKUP_CRON_TZ = "UTC" by default.
    state = BackupScheduleState.get_or_create_singleton()
    assert state.cron_expr == settings.BACKUP_CRON_EXPR
    assert state.timezone == settings.BACKUP_CRON_TZ


# ---------------------------------------------------------------------------
# Tick uses stored state values
# ---------------------------------------------------------------------------

def test_tick_uses_stored_cron_for_next_run(db, settings):
    """tick_backup_schedule computes next_run_at from the DB row's cron_expr
    and timezone, not directly from settings."""
    settings.BACKUP_CRON_EXPR = "0 3 * * *"
    settings.BACKUP_CRON_TZ = "UTC"
    state = BackupScheduleState.get_or_create_singleton()
    # Override DB to a different cron than settings.
    state.cron_expr = "0 22 * * *"
    state.timezone = "UTC"
    state.active = True
    state.next_run_at = None
    state.save()

    # Tick should initialize next_run_at from the DB cron (22:00), not
    # from the settings cron (03:00).
    tick_backup_schedule()
    state.refresh_from_db()
    assert state.next_run_at is not None
    # The next fire for "0 22 * * *" should be at 22:00.
    assert state.next_run_at.hour == 22 or state.next_run_at.hour == 22 - 0


# ---------------------------------------------------------------------------
# Scheduling decisions (due / not-due / idempotent)
# ---------------------------------------------------------------------------

def test_not_due_backup_does_nothing(backup_state):
    """When next_run_at is in the future, tick returns empty."""
    result = tick_backup_schedule()
    assert result == {}
    backup_state.refresh_from_db()
    assert backup_state.last_run_at is None


def test_inactive_backup_schedule_skipped(backup_state):
    """Inactive schedule never fires even if overdue."""
    backup_state.active = False
    backup_state.next_run_at = dj_tz.now() - timedelta(hours=1)
    backup_state.save()
    result = tick_backup_schedule()
    assert result == {}


def test_missing_next_run_at_gets_initialized(db):
    """When next_run_at is NULL, tick initializes it without firing."""
    state = BackupScheduleState.get_or_create_singleton()
    state.active = True
    state.next_run_at = None
    state.save()
    result = tick_backup_schedule()
    assert result == {}  # Does not fire on initialization tick
    state.refresh_from_db()
    assert state.next_run_at is not None
    assert state.next_run_at > dj_tz.now()


def test_singleton_get_or_create(db):
    """BackupScheduleState is a singleton (pk=1)."""
    s1 = BackupScheduleState.get_or_create_singleton()
    s2 = BackupScheduleState.get_or_create_singleton()
    assert s1.pk == s2.pk == 1


def test_due_backup_fires_and_advances(backup_state, settings, tmp_path):
    """When next_run_at is in the past, the tick fires a real backup,
    records success, and advances next_run_at into the future.

    This test exercises the full backup path (real mysqldump + AES-256-GCM
    encryption) so it only works inside the Docker stack with a real MySQL
    connection and BACKUP_ENCRYPTION_KEY configured.
    """
    import os
    if not os.environ.get("BACKUP_ENCRYPTION_KEY") and not os.environ.get("BACKUP_ENCRYPTION_KEY_FILE"):
        pytest.skip("BACKUP_ENCRYPTION_KEY not set (only available in Docker stack)")

    settings.BACKUP_STORAGE_DIR = tmp_path / "backups"
    backup_state.next_run_at = dj_tz.now() - timedelta(minutes=5)
    backup_state.save()
    old_next = backup_state.next_run_at

    result = tick_backup_schedule()
    assert result.get("status") == "success"
    assert result.get("label")
    assert "next_run_at" in result

    backup_state.refresh_from_db()
    assert backup_state.last_run_status == "success"
    assert backup_state.last_run_at is not None
    assert backup_state.next_run_at > old_next
    assert backup_state.next_run_at > dj_tz.now()


def test_repeat_tick_idempotent_when_not_due(backup_state):
    """After a tick advances next_run_at, an immediate second tick does nothing."""
    # Set to far future — simulating post-fire state
    backup_state.next_run_at = dj_tz.now() + timedelta(hours=23)
    backup_state.last_run_at = dj_tz.now()
    backup_state.last_run_status = "success"
    backup_state.save()

    result = tick_backup_schedule()
    assert result == {}
    backup_state.refresh_from_db()
    # last_run_at unchanged
    assert backup_state.last_run_status == "success"


def test_next_fire_for_backup_cron():
    """Validate that the backup cron expression produces expected firing times."""
    base = datetime(2026, 4, 16, 0, 30, tzinfo=timezone.utc)
    nxt = next_fire("0 1 * * *", tz="UTC", now=base)
    assert nxt == datetime(2026, 4, 16, 1, 0, tzinfo=timezone.utc)

    base2 = datetime(2026, 4, 16, 1, 30, tzinfo=timezone.utc)
    nxt2 = next_fire("0 1 * * *", tz="UTC", now=base2)
    assert nxt2 == datetime(2026, 4, 17, 1, 0, tzinfo=timezone.utc)
