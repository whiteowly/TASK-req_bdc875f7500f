"""Content entries, versions, publish/rollback HTTP views."""
from __future__ import annotations

from typing import Any, Dict

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.platform_common.audit import write_audit
from apps.platform_common.concurrency import check_version, parse_if_match
from apps.platform_common.errors import Forbidden, NotFound, ValidationFailure
from apps.platform_common.permissions import (
    has_capability,
    require_any_capability,
    require_authenticated,
    require_capability,
)

from . import services
from .models import ContentEntry, ContentVersion


def _entry_repr(e: ContentEntry) -> Dict[str, Any]:
    return {
        "id": e.id,
        "content_type": e.content_type,
        "slug": e.slug,
        "title": e.title,
        "current_published_version_id": e.current_published_version_id,
        "created_at": e.created_at.isoformat(),
        "updated_at": e.updated_at.isoformat(),
        "version": e.version,
    }


def _ver_repr(v: ContentVersion) -> Dict[str, Any]:
    return {
        "id": v.id,
        "entry_id": v.entry_id,
        "state": v.state,
        "operator_user_id": v.operator_user_id,
        "changed_fields": v.changed_fields,
        "reason": v.reason,
        "created_at": v.created_at.isoformat(),
        "body": v.body,
    }


@api_view(["GET", "POST"])
def entries(request):
    require_authenticated(request)
    if request.method == "GET":
        require_any_capability(request, ("content:read_published", "content:read_all"))
        qs = ContentEntry.objects.all().order_by("-created_at")
        if not has_capability(request, "content:read_all"):
            qs = qs.filter(current_published_version_id__isnull=False)
        ctype = request.query_params.get("content_type")
        if ctype:
            qs = qs.filter(content_type=ctype)
        return Response({"entries": [_entry_repr(e) for e in qs[:200]]})

    require_capability(request, "content:write")
    payload = request.data or {}
    entry = services.create_entry(
        content_type=payload.get("content_type"),
        slug=(payload.get("slug") or "").strip(),
        title=(payload.get("title") or "").strip(),
        created_by=request.actor,
    )
    write_audit(
        actor=request.actor,
        action="content.create_entry",
        object_type="content_entry",
        object_id=entry.id,
        request=request,
        payload_after={"slug": entry.slug, "content_type": entry.content_type},
    )
    return Response(_entry_repr(entry), status=status.HTTP_201_CREATED)


def _get_entry(entry_id: str) -> ContentEntry:
    try:
        return ContentEntry.objects.get(id=entry_id)
    except ContentEntry.DoesNotExist as exc:
        raise NotFound("Entry not found") from exc


@api_view(["GET", "PATCH"])
def entry_detail(request, entry_id: str):
    require_authenticated(request)
    if request.method == "GET":
        require_any_capability(request, ("content:read_published", "content:read_all"))
    entry = _get_entry(entry_id)
    if not has_capability(request, "content:read_all"):
        if entry.current_published_version_id is None:
            raise Forbidden("Entry is not published")
    if request.method == "GET":
        body = _entry_repr(entry)
        if entry.current_published_version_id and not has_capability(request, "content:read_all"):
            try:
                pub = entry.versions.get(id=entry.current_published_version_id)
                body["published_body"] = pub.body
            except ContentVersion.DoesNotExist:
                pass
        return Response(body)

    require_capability(request, "content:write")
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(entry.version, expected)
    payload = request.data or {}
    fields_changed = []
    if "title" in payload:
        new_title = (payload["title"] or "").strip()
        if not new_title:
            raise ValidationFailure("title cannot be empty")
        entry.title = new_title
        fields_changed.append("title")
    if not fields_changed:
        raise ValidationFailure("no editable fields supplied")
    entry.version += 1
    entry.save(update_fields=[*fields_changed, "version", "updated_at"])
    write_audit(
        actor=request.actor,
        action="content.update_entry",
        object_type="content_entry",
        object_id=entry.id,
        request=request,
        payload_after={"changed": fields_changed},
    )
    return Response(_entry_repr(entry))


@api_view(["GET", "POST"])
def versions(request, entry_id: str):
    require_authenticated(request)
    entry = _get_entry(entry_id)
    if request.method == "GET":
        require_any_capability(request, ("content:read_published", "content:read_all"))
        qs = entry.versions.all().order_by("-created_at")
        if not has_capability(request, "content:read_all"):
            qs = qs.filter(state="published")
        return Response({"versions": [_ver_repr(v) for v in qs[:200]]})

    require_capability(request, "content:write")
    payload = request.data or {}
    body = payload.get("body") or ""
    reason = payload.get("reason") or ""
    v = services.add_version(
        entry=entry,
        body=body,
        operator=request.actor,
        changed_fields=payload.get("changed_fields") or ["body"],
        reason=reason,
    )
    write_audit(
        actor=request.actor,
        action="content.add_version",
        object_type="content_version",
        object_id=v.id,
        request=request,
        payload_after={"entry_id": entry.id, "state": v.state},
    )
    return Response(_ver_repr(v), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def publish(request, entry_id: str):
    require_capability(request, "content:publish")
    entry = _get_entry(entry_id)
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(entry.version, expected)
    payload = request.data or {}
    version_id = payload.get("version_id")
    if not version_id:
        raise ValidationFailure("version_id required")
    new_pub = services.publish(
        entry=entry,
        version_id=version_id,
        reason=payload.get("reason") or "",
        operator=request.actor,
    )
    write_audit(
        actor=request.actor,
        action="content.publish",
        object_type="content_version",
        object_id=new_pub.id,
        request=request,
        payload_after={"entry_id": entry.id, "version_id": new_pub.id},
    )
    entry.refresh_from_db()
    return Response({"entry": _entry_repr(entry), "version": _ver_repr(new_pub)})


@api_view(["POST"])
def rollback(request, entry_id: str):
    require_capability(request, "content:rollback")
    entry = _get_entry(entry_id)
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(entry.version, expected)
    payload = request.data or {}
    target_version_id = payload.get("target_version_id") or payload.get("version_id")
    if not target_version_id:
        raise ValidationFailure("target_version_id required")
    rolled = services.rollback(
        entry=entry,
        target_version_id=target_version_id,
        reason=payload.get("reason") or "",
        operator=request.actor,
    )
    write_audit(
        actor=request.actor,
        action="content.rollback",
        object_type="content_version",
        object_id=rolled.id,
        request=request,
        payload_after={"entry_id": entry.id, "target_version_id": target_version_id},
    )
    entry.refresh_from_db()
    return Response({"entry": _entry_repr(entry), "version": _ver_repr(rolled)})


@api_view(["GET"])
def diff(request, entry_id: str):
    require_capability(request, "content:read_all")
    entry = _get_entry(entry_id)
    a_id = request.query_params.get("from_version_id")
    b_id = request.query_params.get("to_version_id")
    if not a_id or not b_id:
        raise ValidationFailure("from_version_id and to_version_id required")
    try:
        a = entry.versions.get(id=a_id)
        b = entry.versions.get(id=b_id)
    except ContentVersion.DoesNotExist as exc:
        raise NotFound("version not found") from exc
    return Response(services.diff_versions(a, b))
