"""Idempotency helpers — 24-hour dedupe window matching the API spec."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .errors import IdempotencyKeyConflict
from .models import IdempotencyKey


# Endpoints that REQUIRE an Idempotency-Key header. Listed by route prefix +
# HTTP method per the API spec.
REQUIRED_IDEMPOTENT_ROUTES = (
    ("POST", "/api/v1/tickets"),
    ("POST", "/api/v1/reports/runs"),
    ("POST", "/api/v1/reports/runs/"),  # /reports/runs/{id}/exports
    ("POST", "/api/v1/tickets/"),       # /tickets/{id}/backfills
)


def hash_request(body: bytes) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def lookup(
    *, key: str, actor_user_id: str, method: str, path: str
) -> Optional[IdempotencyKey]:
    now = timezone.now()
    qs = IdempotencyKey.objects.filter(
        key=key,
        actor_user_id=actor_user_id,
        method=method,
        path=path,
        expires_at__gt=now,
    )
    return qs.first()


def store(
    *,
    key: str,
    actor_user_id: str,
    method: str,
    path: str,
    request_hash: str,
    response_status: int,
    response_body: Any,
) -> IdempotencyKey:
    expires_at = timezone.now() + timedelta(seconds=settings.IDEMPOTENCY_WINDOW_SECONDS)
    try:
        with transaction.atomic():
            return IdempotencyKey.objects.create(
                key=key,
                actor_user_id=actor_user_id,
                method=method,
                path=path,
                request_hash=request_hash,
                response_status=response_status,
                response_body=response_body,
                expires_at=expires_at,
            )
    except IntegrityError:
        # Existing entry for the same (key, actor, method, path)
        existing = lookup(key=key, actor_user_id=actor_user_id, method=method, path=path)
        if existing is None:  # pragma: no cover - extremely unlikely
            raise
        if existing.request_hash != request_hash:
            raise IdempotencyKeyConflict(
                "Idempotency key reused with a different payload",
                details={"existing_status": existing.response_status},
            )
        return existing
