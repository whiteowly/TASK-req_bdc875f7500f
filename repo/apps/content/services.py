"""Content publishing, rollback, diff services with strict invariants."""
from __future__ import annotations

import html
from datetime import timedelta
from typing import Iterable, Optional

from django.db import transaction
from django.utils import timezone

from apps.platform_common.errors import (
    Conflict,
    DomainRuleViolation,
    NotFound,
    ValidationFailure,
)

from .models import (
    CONTENT_TYPES,
    ContentEntry,
    ContentVersion,
    VERSION_STATES,
)


PUBLISH_REASON_MIN = 10
ROLLBACK_WINDOW_DAYS = 30


def sanitize_body(body: str) -> str:
    """Sanitize content body for safe downstream rendering.

    The render policy escapes HTML special characters so stored XSS payloads
    cannot be rendered as live markup.
    """
    if body is None:
        return ""
    return html.escape(body, quote=True)


def create_entry(*, content_type: str, slug: str, title: str, created_by) -> ContentEntry:
    if content_type not in CONTENT_TYPES:
        raise ValidationFailure("invalid content_type", details={"allowed": list(CONTENT_TYPES)})
    if not slug or not title:
        raise ValidationFailure("slug and title required")
    if ContentEntry.objects.filter(slug=slug).exists():
        raise Conflict("slug already exists", code="slug_conflict")
    return ContentEntry.objects.create(
        content_type=content_type, slug=slug, title=title, created_by=created_by
    )


def add_version(*, entry: ContentEntry, body: str, operator,
                changed_fields: Optional[Iterable[str]] = None,
                reason: str = "") -> ContentVersion:
    return ContentVersion.objects.create(
        entry=entry,
        body=sanitize_body(body),
        state="draft",
        operator_user=operator,
        changed_fields=list(changed_fields or ["body"]),
        reason=reason,
    )


def publish(*, entry: ContentEntry, version_id: str, reason: str, operator) -> ContentVersion:
    if not reason or len(reason.strip()) < PUBLISH_REASON_MIN:
        raise DomainRuleViolation(
            f"publish reason must be at least {PUBLISH_REASON_MIN} characters",
            code="publish_reason_too_short",
        )
    with transaction.atomic():
        entry = ContentEntry.objects.select_for_update().get(pk=entry.pk)
        try:
            target = entry.versions.select_for_update().get(id=version_id)
        except ContentVersion.DoesNotExist as exc:
            raise NotFound("version not found") from exc
        # Demote any currently published version.
        ContentVersion.objects.filter(entry=entry, published_key=entry.id).update(
            state="rolled_back", published_key=None
        )
        target.state = "published"
        target.published_key = entry.id
        target.reason = reason.strip()
        target.changed_fields = list(set(target.changed_fields or []) | {"state"})
        target.save(update_fields=["state", "published_key", "reason", "changed_fields"])
        entry.current_published_version_id = target.id
        entry.version += 1
        entry.save(update_fields=["current_published_version_id", "version", "updated_at"])
    return target


def rollback(*, entry: ContentEntry, target_version_id: str, reason: str, operator) -> ContentVersion:
    if not reason or not reason.strip():
        raise ValidationFailure("reason required")
    try:
        target = entry.versions.get(id=target_version_id)
    except ContentVersion.DoesNotExist as exc:
        raise NotFound("target version not found") from exc
    cutoff = timezone.now() - timedelta(days=ROLLBACK_WINDOW_DAYS)
    if target.created_at < cutoff:
        raise DomainRuleViolation(
            f"rollback only allowed to versions created within last {ROLLBACK_WINDOW_DAYS} days",
            code="rollback_window_exceeded",
        )
    with transaction.atomic():
        entry = ContentEntry.objects.select_for_update().get(pk=entry.pk)
        ContentVersion.objects.filter(entry=entry, published_key=entry.id).update(
            state="rolled_back", published_key=None
        )
        new_version = ContentVersion.objects.create(
            entry=entry,
            body=target.body,
            state="published",
            published_key=entry.id,
            operator_user=operator,
            changed_fields=["rollback_to:" + target.id],
            reason=reason.strip(),
        )
        entry.current_published_version_id = new_version.id
        entry.version += 1
        entry.save(update_fields=["current_published_version_id", "version", "updated_at"])
    return new_version


def diff_versions(a: ContentVersion, b: ContentVersion) -> dict:
    return {
        "from_version_id": a.id,
        "to_version_id": b.id,
        "changed_fields": ["body"] if a.body != b.body else [],
        "from_body": a.body,
        "to_body": b.body,
    }
