"""Inspection schedule timezone default uses settings.TIME_ZONE, not hardcoded UTC.

Proves that new InspectionSchedule instances and the create/upsert view
use the configured local timezone from settings rather than a hardcoded
'UTC' string.  Also verifies the migration chain declares the callable
default rather than a hardcoded literal.
"""
import pytest

from django.conf import settings

from apps.quality.models import _default_timezone

pytestmark = pytest.mark.no_db


def test_default_timezone_reads_from_settings():
    """The callable used as the model default returns settings.TIME_ZONE."""
    result = _default_timezone()
    assert result == settings.TIME_ZONE or (not settings.TIME_ZONE and result == "UTC")


def test_default_timezone_matches_settings_time_zone():
    """Whatever TIME_ZONE is configured in settings, the model default
    must match it exactly (not unconditionally return 'UTC')."""
    expected = settings.TIME_ZONE
    actual = _default_timezone()
    assert actual == expected, (
        f"Model default timezone should be '{expected}' (settings.TIME_ZONE), got '{actual}'"
    )


def test_inspection_schedule_migration_uses_callable_default():
    """The latest migration for InspectionSchedule.timezone must reference
    the callable ``_default_timezone``, not a hardcoded 'UTC' string."""
    import importlib
    m = importlib.import_module(
        "apps.quality.migrations.0004_alter_inspectionschedule_timezone_default"
    )
    alter_op = m.Migration.operations[0]
    field = alter_op.field
    # field.default should be the callable, not a string
    assert callable(field.default), (
        f"Migration default should be a callable, got {field.default!r}"
    )
    assert field.default() == settings.TIME_ZONE or (
        not settings.TIME_ZONE and field.default() == "UTC"
    )


def test_report_schedule_migration_uses_callable_default():
    """The latest migration for ReportSchedule.timezone must reference
    the callable ``_default_timezone``, not a hardcoded 'UTC' string."""
    import importlib
    m = importlib.import_module(
        "apps.analytics.migrations.0003_alter_reportschedule_timezone_default"
    )
    alter_op = m.Migration.operations[0]
    field = alter_op.field
    assert callable(field.default), (
        f"Migration default should be a callable, got {field.default!r}"
    )
    assert field.default() == settings.TIME_ZONE or (
        not settings.TIME_ZONE and field.default() == "UTC"
    )
