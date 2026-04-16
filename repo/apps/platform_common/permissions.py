"""Capability-based permission gate used by views."""
from __future__ import annotations

from typing import Iterable

from .errors import Forbidden, Unauthorized


def require_authenticated(request) -> None:
    if request.actor is None:
        raise Unauthorized("Authentication required")


def require_capability(request, capability: str) -> None:
    require_authenticated(request)
    if capability not in request.actor_capabilities:
        raise Forbidden(
            "Missing required capability",
            details={"required": capability},
        )


def require_any_capability(request, capabilities: Iterable[str]) -> None:
    require_authenticated(request)
    caps = set(capabilities)
    if not (caps & request.actor_capabilities):
        raise Forbidden(
            "Missing required capability",
            details={"required_any_of": sorted(caps)},
        )


def has_capability(request, capability: str) -> bool:
    return request.actor is not None and capability in request.actor_capabilities
