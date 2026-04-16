"""Cross-cutting middleware: request id, auth, idempotency, rate limit, errors."""
from __future__ import annotations

import json
import secrets
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from .client_ip import client_ip as _client_ip_helper
from .errors import build_envelope
from .idempotency import hash_request, lookup, store
from .logging_utils import set_request_id
from .models import IdempotencyKey, RateLimitCounter


def _new_request_id() -> str:
    return "req_" + secrets.token_hex(12)


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid = request.headers.get("X-Request-Id") or _new_request_id()
        request.request_id = rid
        set_request_id(rid)
        response = self.get_response(request)
        response.headers["X-Request-Id"] = rid
        return response


class ErrorHandlingMiddleware:
    """Catches uncaught exceptions and returns the documented error envelope."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exc):  # type: ignore[no-untyped-def]
        body = build_envelope(
            code="internal_error",
            message="Internal server error",
            details={"type": exc.__class__.__name__},
            request_id=getattr(request, "request_id", ""),
        )
        return JsonResponse(body, status=500)


class AuthenticationMiddleware:
    """Resolves the bearer token to a session+user, or leaves request anonymous.

    Endpoint-level auth requirements are enforced inside the views. This
    middleware never raises so that the public ``POST /auth/login`` path can
    proceed without credentials.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.session_obj = None
        request.actor = None
        request.actor_roles = []
        request.actor_capabilities = set()
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            self._resolve_session(request, token)
        return self.get_response(request)

    def _resolve_session(self, request, token: str) -> None:
        from apps.identity.models import Session
        from apps.identity.services import token_hash
        from apps.authorization.services import resolve_capabilities

        try:
            session = Session.objects.select_related("user").get(token_hash=token_hash(token))
        except Session.DoesNotExist:
            return
        if session.is_revoked() or session.is_expired():
            return
        request.session_obj = session
        request.actor = session.user
        request.actor_roles, request.actor_capabilities = resolve_capabilities(session.user)


class RateLimitMiddleware:
    """Fixed-window rate limiting on per-user and per-IP scopes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip non-API paths to keep things simple.
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        now = timezone.now()
        bucket = now.replace(second=0, microsecond=0)

        ip = self._client_ip(request)
        if ip:
            allowed_ip = self._tick("ip", ip, bucket, settings.RATE_LIMIT_PER_IP_PER_MIN)
            if not allowed_ip:
                return self._throttled(request)

        if request.actor is not None:
            allowed_user = self._tick(
                "user", str(request.actor.id), bucket, settings.RATE_LIMIT_PER_USER_PER_MIN
            )
            if not allowed_user:
                return self._throttled(request)

        return self.get_response(request)

    @staticmethod
    def _client_ip(request) -> str:
        """Delegate to the centralized IP extraction helper."""
        return _client_ip_helper(request)

    @staticmethod
    def _tick(scope: str, key: str, bucket, limit: int) -> bool:
        with transaction.atomic():
            counter, _ = RateLimitCounter.objects.select_for_update().get_or_create(
                scope=scope, bucket_key=key, window_start=bucket, defaults={"count": 0}
            )
            if counter.count >= limit:
                return False
            counter.count += 1
            counter.save(update_fields=["count"])
        return True

    @staticmethod
    def _throttled(request) -> JsonResponse:
        body = build_envelope(
            code="throttled",
            message="Rate limit exceeded",
            details={
                "user_per_min": settings.RATE_LIMIT_PER_USER_PER_MIN,
                "ip_per_min": settings.RATE_LIMIT_PER_IP_PER_MIN,
            },
            request_id=getattr(request, "request_id", ""),
        )
        resp = JsonResponse(body, status=429)
        resp["Retry-After"] = "60"
        return resp


class IdempotencyMiddleware:
    """Replays prior responses for matching ``Idempotency-Key`` writes.

    Routes listed in ``REQUIRED_ROUTES`` *must* carry the header — a
    missing key produces ``400 idempotency_key_required``. All other
    ``DUPE_PREFIXES`` routes are opportunistic (key is used if present).
    """

    DUPE_PREFIXES = ("/api/v1/tickets", "/api/v1/reports/runs", "/api/v1/exports")

    # Exact path or prefix that REQUIRE the header on POST.
    REQUIRED_ROUTES = (
        "/api/v1/tickets",
        "/api/v1/reports/runs",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _requires_key(path: str) -> bool:
        """Return True when this POST path must carry Idempotency-Key."""
        # /api/v1/tickets (list create) and /api/v1/tickets/<id>/backfills
        if path == "/api/v1/tickets" or path.endswith("/backfills"):
            return True
        # /api/v1/reports/runs (create) and /api/v1/reports/runs/<id>/exports
        if path == "/api/v1/reports/runs" or path.endswith("/exports"):
            return True
        return False

    def __call__(self, request):
        if request.method != "POST" or request.actor is None:
            return self.get_response(request)
        if not any(request.path.startswith(p) for p in self.DUPE_PREFIXES):
            return self.get_response(request)
        key = request.headers.get("Idempotency-Key")
        if not key:
            if self._requires_key(request.path):
                body = build_envelope(
                    code="idempotency_key_required",
                    message="Idempotency-Key header is required for this endpoint",
                    details={"header": "Idempotency-Key"},
                    request_id=getattr(request, "request_id", ""),
                )
                return JsonResponse(body, status=400)
            return self.get_response(request)

        body_bytes = request.body or b""
        rh = hash_request(body_bytes)
        actor_id = str(request.actor.id)
        existing = lookup(key=key, actor_user_id=actor_id, method=request.method, path=request.path)
        if existing is not None:
            from .errors import IdempotencyKeyConflict
            if existing.request_hash != rh:
                envelope = build_envelope(
                    code="idempotency_key_conflict",
                    message="Idempotency key reused with a different payload",
                    details={"existing_status": existing.response_status},
                    request_id=request.request_id,
                )
                return JsonResponse(envelope, status=409)
            return JsonResponse(existing.response_body, status=existing.response_status)

        # Need to read body before passing on (already consumed by .body access).
        request._idempotency_context = {
            "key": key,
            "actor_user_id": actor_id,
            "method": request.method,
            "path": request.path,
            "request_hash": rh,
        }
        response = self.get_response(request)
        if 200 <= response.status_code < 500 and response.status_code not in (401, 403, 429):
            try:
                payload = json.loads(response.content.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                payload = {}
            store(
                response_status=response.status_code,
                response_body=payload,
                **request._idempotency_context,
            )
        return response
