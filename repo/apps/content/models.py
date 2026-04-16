from __future__ import annotations

from django.db import models

from apps.identity.models import User
from apps.platform_common.fields import EncryptedTextField
from apps.platform_common.ids import new_id


CONTENT_TYPES = ("poetry", "tribute")
VERSION_STATES = ("draft", "published", "rolled_back")


def _ent_id() -> str:
    return new_id("ent")


def _ver_id() -> str:
    return new_id("ver")


class ContentEntry(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_ent_id, editable=False)
    content_type = models.CharField(max_length=16)
    slug = models.CharField(max_length=128, unique=True)
    title = models.CharField(max_length=255)
    current_published_version_id = models.CharField(max_length=40, null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="content_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "content_entries"


class ContentVersion(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_ver_id, editable=False)
    entry = models.ForeignKey(ContentEntry, on_delete=models.CASCADE, related_name="versions")
    body = EncryptedTextField()
    state = models.CharField(max_length=16, default="draft")
    operator_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="content_versions")
    changed_fields = models.JSONField(default=list, blank=True)
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    # ``published_key`` is used to enforce single-published-per-entry via a
    # partial-style unique index. NULL when the row is not currently published.
    published_key = models.CharField(max_length=40, null=True, blank=True)

    class Meta:
        db_table = "content_versions"
        constraints = [
            # MySQL allows multiple NULLs in a unique index, so this enforces
            # at most one row per entry where ``published_key = entry_id``.
            models.UniqueConstraint(
                fields=["published_key"], name="uniq_single_published_per_entry"
            ),
        ]
