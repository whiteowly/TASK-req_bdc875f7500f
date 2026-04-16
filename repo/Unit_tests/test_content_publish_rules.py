"""Content publish/rollback rules + single-published-version invariant."""
from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from apps.content import services as content_services
from apps.content.models import ContentEntry, ContentVersion
from apps.platform_common.errors import DomainRuleViolation, ValidationFailure


@pytest.fixture
def entry(db):
    return ContentEntry.objects.create(
        content_type="poetry", slug="alpha", title="Alpha"
    )


def test_publish_rejects_short_reason(db, entry):
    v = content_services.add_version(entry=entry, body="hi", operator=None)
    with pytest.raises(DomainRuleViolation):
        content_services.publish(entry=entry, version_id=v.id,
                                 reason="too short", operator=None)


def test_publish_accepts_minimum_length_reason(db, entry):
    v = content_services.add_version(entry=entry, body="hi", operator=None)
    out = content_services.publish(
        entry=entry, version_id=v.id,
        reason="adequate reason text", operator=None,
    )
    assert out.state == "published"
    entry.refresh_from_db()
    assert entry.current_published_version_id == out.id


def test_only_one_published_version_per_entry(db, entry):
    v1 = content_services.add_version(entry=entry, body="one", operator=None)
    v2 = content_services.add_version(entry=entry, body="two", operator=None)
    content_services.publish(entry=entry, version_id=v1.id,
                             reason="initial publish text", operator=None)
    content_services.publish(entry=entry, version_id=v2.id,
                             reason="superseded by version two", operator=None)
    published = ContentVersion.objects.filter(entry=entry, state="published").count()
    assert published == 1
    entry.refresh_from_db()
    assert entry.current_published_version_id == v2.id


def test_rollback_within_window_succeeds(db, entry):
    v = content_services.add_version(entry=entry, body="orig", operator=None)
    content_services.publish(entry=entry, version_id=v.id,
                             reason="initial publish text", operator=None)
    new_pub = content_services.rollback(
        entry=entry, target_version_id=v.id,
        reason="rolled back due to issue", operator=None,
    )
    assert new_pub.state == "published"
    entry.refresh_from_db()
    assert entry.current_published_version_id == new_pub.id


def test_rollback_outside_30_day_window_rejected(db, entry):
    old = content_services.add_version(entry=entry, body="ancient", operator=None)
    # Backdate the version beyond the window.
    ContentVersion.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )
    old.refresh_from_db()
    with pytest.raises(DomainRuleViolation):
        content_services.rollback(
            entry=entry, target_version_id=old.id,
            reason="should be rejected by window guard", operator=None,
        )


def test_sanitize_body_escapes_html():
    out = content_services.sanitize_body("<script>alert('xss')</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
