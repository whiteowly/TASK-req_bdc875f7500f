"""Users, sessions, roles."""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.platform_common.ids import new_id


def _new_user_id() -> str:
    return new_id("usr")


def _new_session_id() -> str:
    return new_id("sess")


def _new_role_id() -> str:
    return new_id("rol")


def _new_grant_id() -> str:
    return new_id("grant")


class User(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_new_user_id, editable=False)
    username = models.CharField(max_length=64, unique=True)
    password_hash = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "users"


class Role(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_new_role_id, editable=False)
    name = models.CharField(max_length=32, unique=True)

    class Meta:
        db_table = "roles"


class UserRole(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_users")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_roles"
        unique_together = (("user", "role"),)


class PermissionGrant(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_new_grant_id, editable=False)
    principal_type = models.CharField(max_length=16)
    principal_id = models.CharField(max_length=40)
    capability = models.CharField(max_length=128)
    scope = models.JSONField(default=dict, blank=True)
    granted_by = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "permission_grants"
        indexes = [models.Index(fields=["principal_type", "principal_id"])]


class Session(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_new_session_id, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sessions"
        indexes = [models.Index(fields=["expires_at"])]

    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    def is_revoked(self) -> bool:
        return self.revoked_at is not None
