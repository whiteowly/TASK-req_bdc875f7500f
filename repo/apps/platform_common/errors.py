"""Normalized error envelope and DRF exception handling."""
from __future__ import annotations

from typing import Any, Dict, Optional

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class DomainError(APIException):
    """Base error producing the documented error envelope."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "validation_error"
    default_detail = "Invalid request"

    def __init__(self, message: str = "", *, code: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None,
                 http_status: Optional[int] = None) -> None:
        if message:
            self.default_detail = message
        if code:
            self.default_code = code
        if http_status is not None:
            self.status_code = http_status
        self.details = details or {}
        super().__init__(detail=self.default_detail, code=self.default_code)


class ValidationFailure(DomainError):
    status_code = 400
    default_code = "validation_error"


class Unauthorized(DomainError):
    status_code = 401
    default_code = "unauthorized"


class Forbidden(DomainError):
    status_code = 403
    default_code = "forbidden"


class NotFound(DomainError):
    status_code = 404
    default_code = "not_found"


class Conflict(DomainError):
    status_code = 409
    default_code = "conflict"


class VersionConflict(Conflict):
    default_code = "version_conflict"


class IdempotencyKeyConflict(Conflict):
    default_code = "idempotency_key_conflict"


class InvalidStateTransition(Conflict):
    default_code = "invalid_state_transition"


class ExportExpired(DomainError):
    status_code = 410
    default_code = "export_expired"


class DomainRuleViolation(DomainError):
    status_code = 422
    default_code = "domain_rule_violation"


class Throttled(DomainError):
    status_code = 429
    default_code = "throttled"


def build_envelope(code: str, message: str, *, details: Optional[Dict[str, Any]] = None,
                   request_id: str = "") -> Dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }


def exception_handler(exc, context):  # type: ignore[no-untyped-def]
    request = context.get("request") if context else None
    request_id = getattr(request, "request_id", "") if request else ""

    if isinstance(exc, DomainError):
        body = build_envelope(
            code=exc.default_code,
            message=str(exc.default_detail),
            details=exc.details,
            request_id=request_id,
        )
        return Response(body, status=exc.status_code)

    response = drf_exception_handler(exc, context)
    if response is not None:
        code = "validation_error"
        if response.status_code == 401:
            code = "unauthorized"
        elif response.status_code == 403:
            code = "forbidden"
        elif response.status_code == 404:
            code = "not_found"
        elif response.status_code == 405:
            code = "method_not_allowed"
        elif response.status_code == 429:
            code = "throttled"
        elif response.status_code == 409:
            code = "conflict"
        details = response.data if isinstance(response.data, dict) else {"detail": response.data}
        body = build_envelope(
            code=code,
            message=str(details.get("detail", "Request failed")) if isinstance(details, dict) else "Request failed",
            details=details if isinstance(details, dict) else {"detail": details},
            request_id=request_id,
        )
        response.data = body
        return response
    return None
