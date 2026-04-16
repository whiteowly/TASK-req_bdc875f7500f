"""Hierarchical role inheritance and capability resolution.

Roles: ``administrator`` ⊃ ``operations`` ⊃ ``user``.

Audit-log export remains administrator-only and is **not** part of the
operations capability set even via inheritance.
"""
from __future__ import annotations

from typing import Iterable, Set, Tuple

# Capability sets per base role
USER_CAPS: Set[str] = {
    "datasets:read",
    "datasets:query",
    "content:read_published",
    "reports:read",
    "reports:run",
    "exports:read_own",
}

OPERATIONS_CAPS: Set[str] = {
    "datasets:write",
    "metadata:write",
    "lineage:read",
    "lineage:write",
    "quality:read",
    "quality:write",
    "quality:trigger",
    "schedules:write",
    "tickets:read",
    "tickets:write",
    "tickets:transition",
    "tickets:assign",
    "tickets:remediate",
    "tickets:backfill",
    "content:read_all",
    "content:write",
    "content:publish",
    "content:rollback",
    "reports:write",
    "exports:write",
    "exports:read_all",
    "monitoring:read",
    "monitoring:write_event",
}

ADMIN_CAPS: Set[str] = {
    "users:manage",
    "permissions:grant",
    "audit:read",
    "audit:export",  # audit export is administrator-only
    "encryption:manage",
    "backups:manage",
}


def caps_for_role(name: str) -> Set[str]:
    if name == "user":
        return set(USER_CAPS)
    if name == "operations":
        return USER_CAPS | OPERATIONS_CAPS
    if name == "administrator":
        return USER_CAPS | OPERATIONS_CAPS | ADMIN_CAPS
    return set()


def resolve_capabilities(user) -> Tuple[list, set]:
    """Return ``(role_names, capability_set)`` for the user.

    Includes capabilities granted explicitly via :class:`PermissionGrant`.
    """
    from apps.identity.models import PermissionGrant

    role_names = sorted(
        user.user_roles.select_related("role").values_list("role__name", flat=True).distinct()
    )
    caps: Set[str] = set()
    for r in role_names:
        caps |= caps_for_role(r)

    grants = PermissionGrant.objects.filter(principal_type="user", principal_id=user.id)
    for g in grants:
        caps.add(g.capability)
    return role_names, caps
