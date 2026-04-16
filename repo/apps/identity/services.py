"""User and session domain services."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from apps.platform_common.errors import (
    Conflict,
    Forbidden,
    NotFound,
    Unauthorized,
    ValidationFailure,
)

from .models import Role, Session, User, UserRole

VALID_ROLES = ("administrator", "operations", "user")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(plain: str) -> str:
    if not plain or len(plain) < 8:
        raise ValidationFailure("Password must be at least 8 characters")
    # Argon2id via Django's hasher API. The configured hasher in settings
    # determines the algorithm (Argon2 first, PBKDF2 fallback).
    return make_password(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return check_password(plain or "", hashed or "")


def ensure_seed_roles() -> None:
    for name in VALID_ROLES:
        Role.objects.get_or_create(name=name)


def create_user(*, username: str, password: str, roles=None) -> User:
    if not username or not username.strip():
        raise ValidationFailure("username required")
    if User.objects.filter(username=username).exists():
        raise Conflict("Username already exists", code="username_conflict")
    user = User.objects.create(username=username, password_hash=hash_password(password))
    if roles:
        assign_roles(user, roles)
    return user


def assign_roles(user: User, role_names) -> None:
    ensure_seed_roles()
    invalid = [r for r in role_names if r not in VALID_ROLES]
    if invalid:
        raise ValidationFailure(
            "Unknown role(s)", code="invalid_role", details={"invalid": invalid}
        )
    role_objs = list(Role.objects.filter(name__in=role_names))
    with transaction.atomic():
        for role in role_objs:
            UserRole.objects.get_or_create(user=user, role=role)


def login(*, username: str, password: str, ip: str = "", user_agent: str = "") -> tuple[Session, str]:
    try:
        user = User.objects.get(username=username, is_active=True)
    except User.DoesNotExist as exc:
        raise Unauthorized("Invalid credentials", code="invalid_credentials") from exc
    if not verify_password(password, user.password_hash):
        raise Unauthorized("Invalid credentials", code="invalid_credentials")
    token = secrets.token_urlsafe(48)
    session = Session.objects.create(
        user=user,
        token_hash=token_hash(token),
        expires_at=timezone.now() + timedelta(seconds=settings.SESSION_TTL_SECONDS),
        ip=ip[:64],
        user_agent=user_agent[:255],
    )
    return session, token


def revoke_session(session: Session) -> None:
    if session.revoked_at is None:
        session.revoked_at = timezone.now()
        session.save(update_fields=["revoked_at"])


def get_session(session_id: str) -> Session:
    try:
        return Session.objects.select_related("user").get(id=session_id)
    except Session.DoesNotExist as exc:
        raise NotFound("Session not found") from exc


def list_sessions_for(user: User):
    return Session.objects.filter(user=user).order_by("-created_at")
