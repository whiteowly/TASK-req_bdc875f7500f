"""Ticket state machine, remediation, and backfill domain services."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from django.utils import timezone

from apps.platform_common.errors import (
    InvalidStateTransition,
    NotFound,
    ValidationFailure,
)

from .models import (
    ALLOWED_TRANSITIONS,
    BackfillReinspection,
    BackfillRun,
    IssueTicket,
    TICKET_STATES,
    TicketTransition,
)


def is_allowed(from_state: str, to_state: str) -> bool:
    return to_state in ALLOWED_TRANSITIONS.get(from_state, set())


def transition(ticket: IssueTicket, *, to_state: str, reason: str, actor_id: str) -> IssueTicket:
    if to_state not in TICKET_STATES:
        raise ValidationFailure("invalid to_state", details={"allowed": list(TICKET_STATES)})
    if not reason or not reason.strip():
        raise ValidationFailure("reason required for transition")
    if not is_allowed(ticket.state, to_state):
        raise InvalidStateTransition(
            "transition not allowed",
            details={"from": ticket.state, "to": to_state, "allowed": sorted(ALLOWED_TRANSITIONS.get(ticket.state, set()))},
        )
    prior = ticket.state
    ticket.state = to_state
    ticket.version += 1
    ticket.save(update_fields=["state", "version", "updated_at"])
    TicketTransition.objects.create(
        ticket=ticket,
        from_state=prior,
        to_state=to_state,
        reason=reason.strip(),
        transitioned_by=actor_id,
    )
    return ticket


def default_due_date(today: Optional[date] = None) -> date:
    today = today or timezone.now().date()
    return today + timedelta(days=7)


def _resolve_ticket_owner(dataset):
    """Determine the owner for an auto-created ticket.

    Policy (deterministic fallback chain):
    1. If the dataset has metadata with an ``owner`` field that matches a
       username in the system, assign that user.
    2. Otherwise, assign the first active user with the ``operations`` role.
    3. Otherwise, assign the first active ``administrator``.
    4. If none found, leave owner NULL (caller should still create ticket).
    """
    from apps.identity.models import User, UserRole

    # 1. Dataset metadata owner → user lookup
    try:
        md = dataset.metadata
        if md and md.owner:
            try:
                return User.objects.get(username=md.owner, is_active=True)
            except User.DoesNotExist:
                pass
    except Exception:
        pass

    # 2. First active operations user
    ops_ur = (
        UserRole.objects.filter(role__name="operations", user__is_active=True)
        .select_related("user")
        .order_by("user__created_at")
        .first()
    )
    if ops_ur:
        return ops_ur.user

    # 3. First active administrator
    admin_ur = (
        UserRole.objects.filter(role__name="administrator", user__is_active=True)
        .select_related("user")
        .order_by("user__created_at")
        .first()
    )
    if admin_ur:
        return admin_ur.user

    return None


def auto_create_tickets_for_failed_inspection(inspection_run) -> int:
    """Create one ticket per breached P0 result for the given inspection run.

    Each ticket is assigned an owner (via deterministic policy) and an
    initial remediation action so the ticket is actionable immediately.
    """
    from .models import RemediationAction

    owner = _resolve_ticket_owner(inspection_run.dataset)
    created = 0
    for r in inspection_run.results.filter(passed=False, severity_snapshot="P0"):
        ticket = IssueTicket.objects.create(
            dataset=inspection_run.dataset,
            inspection_run=inspection_run,
            rule_result=r,
            title=f"P0 quality breach on dataset {inspection_run.dataset.code}",
            description=f"Rule {r.rule_id} measured={r.measured_value} threshold={r.threshold_snapshot}",
            severity_snapshot=r.severity_snapshot,
            due_date=default_due_date(),
            owner_user=owner,
        )
        TicketTransition.objects.create(
            ticket=ticket,
            from_state="open",
            to_state="open",
            reason="auto-created from failed P0 inspection result",
            transitioned_by="system",
        )
        RemediationAction.objects.create(
            ticket=ticket,
            action_type="investigate_and_fix",
            parameters={
                "rule_id": r.rule_id,
                "measured_value": str(r.measured_value),
                "threshold": str(r.threshold_snapshot),
                "description": (
                    f"Investigate root cause of rule {r.rule_id} breach "
                    f"(measured={r.measured_value}, threshold={r.threshold_snapshot}) "
                    f"and apply corrective action."
                ),
            },
            status="pending",
            created_by="system",
        )
        created += 1
    return created


def record_backfill(*, ticket: IssueTicket, input_fingerprint: str,
                    parameters: dict, operator) -> tuple[BackfillRun, bool]:
    """Idempotent on (ticket, input_fingerprint).

    Returns ``(backfill_run, created)``.
    """
    if not input_fingerprint:
        raise ValidationFailure("input_fingerprint required")
    bf, created = BackfillRun.objects.get_or_create(
        ticket=ticket,
        input_fingerprint=input_fingerprint,
        defaults={
            "affected_record_count": int(parameters.get("affected_record_count", 0)),
            "status": "complete",
            "ended_at": timezone.now(),
            "operator_user": operator,
        },
    )
    if created:
        # Trigger a reinspection of the dataset and link it to this backfill.
        from apps.quality.services import run_inspection
        re_run = run_inspection(dataset=ticket.dataset, actor_id=str(operator.id) if operator else "system")
        BackfillReinspection.objects.create(backfill_run=bf, inspection_run=re_run)
    return bf, created
