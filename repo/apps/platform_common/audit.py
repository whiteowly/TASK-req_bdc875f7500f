"""Audit logging helper used by all mutating endpoints."""
from __future__ import annotations

from typing import Any, Optional

from .client_ip import client_ip


def write_audit(
    *,
    actor,
    action: str,
    object_type: str,
    object_id: str,
    request,
    payload_before: Optional[dict] = None,
    payload_after: Optional[dict] = None,
) -> None:
    """Write an immutable audit record. Imported lazily to avoid app cycles."""
    from apps.audit_monitoring.models import AuditLog

    AuditLog.objects.create(
        actor_user_id=str(actor.id) if actor is not None else "",
        action=action,
        object_type=object_type,
        object_id=object_id,
        request_id=getattr(request, "request_id", ""),
        ip=client_ip(request),
        payload_before=payload_before or {},
        payload_after=payload_after or {},
    )
