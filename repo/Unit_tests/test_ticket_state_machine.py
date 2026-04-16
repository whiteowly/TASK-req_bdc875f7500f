"""Ticket state machine semantics — exact transitions from the spec."""
import pytest

from apps.platform_common.errors import (
    InvalidStateTransition,
    ValidationFailure,
)
from apps.tickets.models import (
    ALLOWED_TRANSITIONS,
    IssueTicket,
    TICKET_STATES,
)
from apps.tickets.services import default_due_date, is_allowed, transition


def test_states_match_spec_exactly():
    assert set(TICKET_STATES) == {"open", "in_progress", "blocked", "resolved", "closed"}


def test_allowed_transitions_match_spec():
    assert ALLOWED_TRANSITIONS == {
        "open": {"in_progress", "blocked", "resolved"},
        "in_progress": {"blocked", "resolved"},
        "blocked": {"in_progress", "resolved"},
        "resolved": {"closed", "in_progress"},
        "closed": set(),
    }


def test_closed_is_terminal():
    assert is_allowed("closed", "open") is False
    assert is_allowed("closed", "in_progress") is False


def test_default_due_date_is_seven_days():
    from datetime import date, timedelta

    today = date(2026, 4, 15)
    assert default_due_date(today) == today + timedelta(days=7)


def test_transition_persists_and_records_history(db):
    ticket = IssueTicket.objects.create(title="t1", state="open")
    transition(ticket, to_state="in_progress", reason="assigned to ETL owner",
               actor_id="usr_actor")
    ticket.refresh_from_db()
    assert ticket.state == "in_progress"
    assert ticket.version == 2
    assert ticket.transitions.count() == 1


def test_transition_rejects_invalid_target(db):
    ticket = IssueTicket.objects.create(title="t1", state="open")
    with pytest.raises(InvalidStateTransition):
        transition(ticket, to_state="closed", reason="invalid jump", actor_id="usr_actor")


def test_transition_requires_reason(db):
    ticket = IssueTicket.objects.create(title="t1", state="open")
    with pytest.raises(ValidationFailure):
        transition(ticket, to_state="in_progress", reason="   ", actor_id="usr_actor")
