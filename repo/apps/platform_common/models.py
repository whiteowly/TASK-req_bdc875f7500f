"""Cross-cutting models: idempotency keys, rate-limit counters, backup schedule."""
from __future__ import annotations

from django.db import models
from django.utils import timezone


class IdempotencyKey(models.Model):
    """Stores the response for an idempotent write so a duplicate replays it."""

    key = models.CharField(max_length=128)
    actor_user_id = models.CharField(max_length=40, blank=True, default="")
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=200)
    request_hash = models.CharField(max_length=128)
    response_status = models.IntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        unique_together = (("key", "actor_user_id", "method", "path"),)
        indexes = [models.Index(fields=["expires_at"])]


class RateLimitCounter(models.Model):
    """Per-(scope, key, window-bucket) counter for fixed-window rate limiting."""

    scope = models.CharField(max_length=16)  # 'user' or 'ip'
    bucket_key = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    count = models.IntegerField(default=0)

    class Meta:
        unique_together = (("scope", "bucket_key", "window_start"),)
        indexes = [models.Index(fields=["window_start"])]


class BackupScheduleState(models.Model):
    """Singleton row tracking the nightly backup schedule state.

    The scheduler checks ``next_run_at`` on each tick; when due it runs a
    backup and advances ``next_run_at`` using the configured cron expression.
    """

    id = models.IntegerField(primary_key=True, default=1, editable=False)
    cron_expr = models.CharField(max_length=64, default="0 1 * * *")
    timezone = models.CharField(max_length=64, default="UTC")
    active = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_status = models.CharField(max_length=32, blank=True, default="")
    last_run_label = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "backup_schedule_state"

    @classmethod
    def get_or_create_singleton(cls):
        """Return the singleton row, creating it from settings on first call.

        First creation seeds ``cron_expr`` and ``timezone`` from
        ``settings.BACKUP_CRON_EXPR`` / ``settings.BACKUP_CRON_TZ`` so the
        env-backed configuration is applied. Subsequent calls return the
        existing DB row unchanged — operator overrides (e.g. via admin or
        direct SQL) are preserved across restarts.
        """
        from django.conf import settings as _s

        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "cron_expr": getattr(_s, "BACKUP_CRON_EXPR", "0 1 * * *"),
                "timezone": getattr(_s, "BACKUP_CRON_TZ", "UTC"),
            },
        )
        return obj
