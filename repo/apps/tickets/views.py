"""Tickets, transitions, remediation, and backfill HTTP views."""
from __future__ import annotations

from typing import Any, Dict

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.models import Dataset
from apps.identity.models import User
from apps.platform_common.audit import write_audit
from apps.platform_common.concurrency import check_version, parse_if_match
from apps.platform_common.errors import NotFound, ValidationFailure
from apps.platform_common.permissions import require_capability

from . import services
from .models import (
    BackfillRun,
    IssueTicket,
    RemediationAction,
    TICKET_STATES,
    TicketTransition,
)


def _ticket_repr(t: IssueTicket) -> Dict[str, Any]:
    return {
        "id": t.id,
        "dataset_id": t.dataset_id,
        "inspection_run_id": t.inspection_run_id,
        "rule_result_id": t.rule_result_id,
        "title": t.title,
        "description": t.description,
        "state": t.state,
        "owner_user_id": t.owner_user_id,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "severity_snapshot": t.severity_snapshot,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
        "version": t.version,
    }


def _bf_repr(b: BackfillRun) -> Dict[str, Any]:
    last_re = b.reinspections.order_by("-created_at").first()
    return {
        "id": b.id,
        "ticket_id": b.ticket_id,
        "input_fingerprint": b.input_fingerprint,
        "affected_record_count": b.affected_record_count,
        "status": b.status,
        "started_at": b.started_at.isoformat(),
        "ended_at": b.ended_at.isoformat() if b.ended_at else None,
        "post_fix_inspection_run_id": last_re.inspection_run_id if last_re else None,
    }


def _get_ticket(ticket_id: str) -> IssueTicket:
    try:
        return IssueTicket.objects.get(id=ticket_id)
    except IssueTicket.DoesNotExist as exc:
        raise NotFound("Ticket not found") from exc


@api_view(["GET", "POST"])
def tickets(request):
    require_capability(request, "tickets:read")
    if request.method == "GET":
        qs = IssueTicket.objects.all().order_by("-created_at")[:200]
        return Response({"tickets": [_ticket_repr(t) for t in qs]})

    require_capability(request, "tickets:write")
    payload = request.data or {}
    title = (payload.get("title") or "").strip()
    description = payload.get("description") or ""
    dataset_id = payload.get("dataset_id")
    if not title:
        raise ValidationFailure("title required")
    ds = None
    if dataset_id:
        try:
            ds = Dataset.objects.get(id=dataset_id)
        except Dataset.DoesNotExist as exc:
            raise NotFound("Dataset not found") from exc
    ticket = IssueTicket.objects.create(
        dataset=ds,
        title=title,
        description=description,
        severity_snapshot=payload.get("severity") or "",
        due_date=services.default_due_date(),
    )
    write_audit(
        actor=request.actor,
        action="tickets.create",
        object_type="ticket",
        object_id=ticket.id,
        request=request,
        payload_after={"title": title, "dataset_id": dataset_id},
    )
    return Response(_ticket_repr(ticket), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def transition(request, ticket_id: str):
    require_capability(request, "tickets:transition")
    ticket = _get_ticket(ticket_id)
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(ticket.version, expected)
    payload = request.data or {}
    to_state = payload.get("to_state")
    reason = payload.get("reason") or ""
    services.transition(ticket, to_state=to_state, reason=reason, actor_id=request.actor.id)
    write_audit(
        actor=request.actor,
        action="tickets.transition",
        object_type="ticket",
        object_id=ticket.id,
        request=request,
        payload_after={"to_state": to_state, "version": ticket.version},
    )
    return Response(_ticket_repr(ticket))


@api_view(["POST"])
def assign(request, ticket_id: str):
    require_capability(request, "tickets:assign")
    ticket = _get_ticket(ticket_id)
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(ticket.version, expected)
    payload = request.data or {}
    user_id = payload.get("user_id")
    if not user_id:
        raise ValidationFailure("user_id required")
    try:
        owner = User.objects.get(id=user_id)
    except User.DoesNotExist as exc:
        raise NotFound("User not found") from exc
    ticket.owner_user = owner
    ticket.version += 1
    ticket.save(update_fields=["owner_user", "version", "updated_at"])
    write_audit(
        actor=request.actor,
        action="tickets.assign",
        object_type="ticket",
        object_id=ticket.id,
        request=request,
        payload_after={"owner_user_id": owner.id},
    )
    return Response(_ticket_repr(ticket))


@api_view(["POST"])
def remediation_action(request, ticket_id: str):
    require_capability(request, "tickets:remediate")
    ticket = _get_ticket(ticket_id)
    expected = parse_if_match(request.headers.get("If-Match"))
    check_version(ticket.version, expected)
    payload = request.data or {}
    action_type = (payload.get("action_type") or "").strip()
    if not action_type:
        raise ValidationFailure("action_type required")
    action = RemediationAction.objects.create(
        ticket=ticket,
        action_type=action_type,
        parameters=payload.get("parameters") or {},
        created_by=request.actor.id,
    )
    write_audit(
        actor=request.actor,
        action="tickets.remediation",
        object_type="remediation_action",
        object_id=action.id,
        request=request,
        payload_after={"ticket_id": ticket.id, "action_type": action_type},
    )
    return Response(
        {
            "id": action.id,
            "ticket_id": ticket.id,
            "action_type": action.action_type,
            "parameters": action.parameters,
            "status": action.status,
            "created_at": action.created_at.isoformat(),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def backfills(request, ticket_id: str):
    require_capability(request, "tickets:backfill")
    ticket = _get_ticket(ticket_id)
    payload = request.data or {}
    fp = (payload.get("input_fingerprint") or "").strip()
    bf, created = services.record_backfill(
        ticket=ticket,
        input_fingerprint=fp,
        parameters=payload.get("parameters") or {},
        operator=request.actor,
    )
    write_audit(
        actor=request.actor,
        action="tickets.backfill",
        object_type="backfill_run",
        object_id=bf.id,
        request=request,
        payload_after={"created": created, "fingerprint": fp},
    )
    return Response(_bf_repr(bf), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["GET"])
def backfill_detail(request, backfill_id: str):
    require_capability(request, "tickets:read")
    try:
        bf = BackfillRun.objects.get(id=backfill_id)
    except BackfillRun.DoesNotExist as exc:
        raise NotFound("Backfill not found") from exc
    return Response(_bf_repr(bf))
