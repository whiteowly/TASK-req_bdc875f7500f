"""Permission grant management endpoints (administrator only)."""
from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.identity.models import PermissionGrant, User
from apps.platform_common.audit import write_audit
from apps.platform_common.errors import NotFound, ValidationFailure
from apps.platform_common.permissions import require_capability


@api_view(["POST"])
def grant_permission(request):
    require_capability(request, "permissions:grant")
    payload = request.data or {}
    principal_type = (payload.get("principal_type") or "user").strip()
    principal_id = (payload.get("principal_id") or "").strip()
    capability = (payload.get("capability") or "").strip()
    scope = payload.get("scope") or {}
    if not principal_id or not capability:
        raise ValidationFailure("principal_id and capability required")
    if principal_type != "user":
        raise ValidationFailure("only principal_type=user is supported")
    if not User.objects.filter(id=principal_id).exists():
        raise NotFound("User not found")
    if capability.startswith("audit:export"):
        # The administrator-only restriction on audit export must not be
        # bypassable via scoped grants — block both the bare capability and
        # any sub-capability variant.
        raise ValidationFailure("audit export grants are not delegable")
    g = PermissionGrant.objects.create(
        principal_type=principal_type,
        principal_id=principal_id,
        capability=capability,
        scope=scope,
        granted_by=request.actor.id,
    )
    write_audit(
        actor=request.actor,
        action="permissions.grant",
        object_type="permission_grant",
        object_id=g.id,
        request=request,
        payload_after={
            "principal_id": principal_id,
            "capability": capability,
            "scope": scope,
        },
    )
    return Response(
        {
            "id": g.id,
            "principal_type": g.principal_type,
            "principal_id": g.principal_id,
            "capability": g.capability,
            "scope": g.scope,
            "granted_by": g.granted_by,
            "created_at": g.created_at.isoformat(),
        },
        status=status.HTTP_201_CREATED,
    )
