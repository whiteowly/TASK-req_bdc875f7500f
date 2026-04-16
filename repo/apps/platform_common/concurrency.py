"""Helpers for optimistic concurrency control via the ``If-Match`` header."""
from __future__ import annotations

from typing import Optional

from .errors import ValidationFailure, VersionConflict


def parse_if_match(header_value: Optional[str]) -> int:
    """Parse the ``If-Match: "<int>"`` header value into an int.

    Raises ``ValidationFailure`` if the header is missing or malformed.
    """
    if not header_value:
        raise ValidationFailure(
            "If-Match header required for this mutation",
            code="if_match_required",
            details={"header": "If-Match"},
        )
    raw = header_value.strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationFailure(
            "If-Match header must be an integer version",
            code="if_match_invalid",
        ) from exc


def check_version(current: int, expected: int) -> None:
    if current != expected:
        raise VersionConflict(
            "If-Match version does not match current resource version.",
            details={"current": current, "expected": expected},
        )
