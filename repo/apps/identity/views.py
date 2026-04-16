"""HTTP views for auth/sessions and user/role management."""
from __future__ import annotations

from typing import Any, Dict

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.platform_common.audit import write_audit
from apps.platform_common.client_ip import client_ip
from apps.platform_common.errors import Forbidden, NotFound, ValidationFailure
from apps.platform_common.permissions import (
    require_authenticated,
    require_capability,
)

from . import services
from .models import Session, User


def _user_repr(user: User) -> Dict[str, Any]:
    role_names = list(
        user.user_roles.select_related("role").values_list("role__name", flat=True)
    )
    return {
        "id": user.id,
        "username": user.username,
        "is_active": user.is_active,
        "roles": sorted(role_names),
        "version": user.version,
    }


def _session_repr(s: Session) -> Dict[str, Any]:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "expires_at": s.expires_at.isoformat(),
        "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
        "created_at": s.created_at.isoformat(),
        "ip": s.ip,
        "user_agent": s.user_agent,
        "is_active": (not s.is_revoked()) and (not s.is_expired()),
    }


@api_view(["POST"])
def login_view(request):
    payload = request.data or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        raise ValidationFailure("username and password required")
    ip = client_ip(request)
    ua = request.headers.get("User-Agent", "")
    session, token = services.login(username=username, password=password, ip=ip, user_agent=ua)
    write_audit(
        actor=session.user,
        action="auth.login",
        object_type="session",
        object_id=session.id,
        request=request,
        payload_after={"session_id": session.id},
    )
    body = {
        "token": token,
        "expires_at": session.expires_at.isoformat(),
        "user": _user_repr(session.user),
    }
    return Response(body, status=status.HTTP_200_OK)


@api_view(["POST"])
def logout_view(request):
    require_authenticated(request)
    services.revoke_session(request.session_obj)
    write_audit(
        actor=request.actor,
        action="auth.logout",
        object_type="session",
        object_id=request.session_obj.id,
        request=request,
    )
    return Response({"revoked": True}, status=status.HTTP_200_OK)


@api_view(["GET"])
def list_sessions_view(request):
    require_authenticated(request)
    user_id = request.query_params.get("user_id")
    if user_id and user_id != request.actor.id:
        require_capability(request, "users:manage")
        try:
            target = User.objects.get(id=user_id)
        except User.DoesNotExist as exc:
            raise NotFound("User not found") from exc
    else:
        target = request.actor
    sessions = list(services.list_sessions_for(target)[:50])
    return Response({"sessions": [_session_repr(s) for s in sessions]})


@api_view(["POST"])
def revoke_session_view(request, session_id: str):
    require_authenticated(request)
    target = services.get_session(session_id)
    if target.user_id != request.actor.id:
        require_capability(request, "users:manage")
    services.revoke_session(target)
    write_audit(
        actor=request.actor,
        action="auth.revoke_session",
        object_type="session",
        object_id=target.id,
        request=request,
    )
    return Response({"revoked": True}, status=status.HTTP_200_OK)


@api_view(["GET", "POST"])
def users_collection(request):
    require_capability(request, "users:manage")
    if request.method == "GET":
        users = list(User.objects.order_by("username")[:200])
        return Response({"users": [_user_repr(u) for u in users]})
    payload = request.data or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    roles = payload.get("roles") or []
    user = services.create_user(username=username, password=password, roles=roles)
    write_audit(
        actor=request.actor,
        action="users.create",
        object_type="user",
        object_id=user.id,
        request=request,
        payload_after={"username": user.username, "roles": roles},
    )
    return Response(_user_repr(user), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
def user_detail(request, user_id: str):
    require_capability(request, "users:manage")
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist as exc:
        raise NotFound("User not found") from exc
    if request.method == "GET":
        return Response(_user_repr(user))

    from apps.platform_common.concurrency import check_version, parse_if_match
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(user.version, expected)

    payload = request.data or {}
    fields_changed = []
    if "is_active" in payload:
        user.is_active = bool(payload["is_active"])
        fields_changed.append("is_active")
    if "password" in payload and payload["password"]:
        user.password_hash = services.hash_password(payload["password"])
        fields_changed.append("password")
    if not fields_changed:
        raise ValidationFailure("no editable fields supplied")
    user.version += 1
    user.save(update_fields=[*fields_changed, "version", "updated_at"])
    write_audit(
        actor=request.actor,
        action="users.update",
        object_type="user",
        object_id=user.id,
        request=request,
        payload_after={"changed": fields_changed},
    )
    return Response(_user_repr(user))


@api_view(["POST"])
def user_roles(request, user_id: str):
    require_capability(request, "users:manage")
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist as exc:
        raise NotFound("User not found") from exc
    payload = request.data or {}
    roles = payload.get("roles") or []
    if not isinstance(roles, list) or not roles:
        raise ValidationFailure("roles list required")
    services.assign_roles(user, roles)
    write_audit(
        actor=request.actor,
        action="users.assign_roles",
        object_type="user",
        object_id=user.id,
        request=request,
        payload_after={"roles": roles},
    )
    return Response(_user_repr(user))
