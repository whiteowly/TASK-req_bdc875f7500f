from __future__ import annotations

from django.db import models

from apps.catalog.models import Dataset
from apps.identity.models import User
from apps.platform_common.ids import new_id
from apps.quality.models import InspectionRuleResult, InspectionRun


def _tkt_id() -> str:
    return new_id("tkt")


def _ttr_id() -> str:
    return new_id("ttr")


def _rem_id() -> str:
    return new_id("rem")


def _bfr_id() -> str:
    return new_id("bfr")


# Exact ticket states allowed by the spec.
TICKET_STATES = ("open", "in_progress", "blocked", "resolved", "closed")


# Allowed transitions: closed is terminal in v1 (no reopen).
ALLOWED_TRANSITIONS = {
    "open": {"in_progress", "blocked", "resolved"},
    "in_progress": {"blocked", "resolved"},
    "blocked": {"in_progress", "resolved"},
    "resolved": {"closed", "in_progress"},
    "closed": set(),
}


class IssueTicket(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_tkt_id, editable=False)
    dataset = models.ForeignKey(Dataset, on_delete=models.SET_NULL, null=True, related_name="tickets")
    inspection_run = models.ForeignKey(InspectionRun, on_delete=models.SET_NULL, null=True, blank=True)
    rule_result = models.ForeignKey(InspectionRuleResult, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    state = models.CharField(max_length=16, default="open")
    owner_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_tickets")
    due_date = models.DateField(null=True, blank=True)
    severity_snapshot = models.CharField(max_length=4, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "issue_tickets"


class TicketTransition(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_ttr_id, editable=False)
    ticket = models.ForeignKey(IssueTicket, on_delete=models.CASCADE, related_name="transitions")
    from_state = models.CharField(max_length=16)
    to_state = models.CharField(max_length=16)
    reason = models.TextField()
    transitioned_by = models.CharField(max_length=40)
    transitioned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_transitions"


class RemediationAction(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_rem_id, editable=False)
    ticket = models.ForeignKey(IssueTicket, on_delete=models.CASCADE, related_name="remediation_actions")
    action_type = models.CharField(max_length=64)
    parameters = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=32, default="pending")
    created_by = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "remediation_actions"


class BackfillRun(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=_bfr_id, editable=False)
    ticket = models.ForeignKey(IssueTicket, on_delete=models.CASCADE, related_name="backfills")
    input_fingerprint = models.CharField(max_length=128)
    affected_record_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, default="queued")
    operator_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="backfill_runs")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "backfill_runs"
        unique_together = (("ticket", "input_fingerprint"),)


class BackfillReinspection(models.Model):
    id = models.BigAutoField(primary_key=True)
    backfill_run = models.ForeignKey(BackfillRun, on_delete=models.CASCADE, related_name="reinspections")
    inspection_run = models.ForeignKey(InspectionRun, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "backfill_reinspections"
