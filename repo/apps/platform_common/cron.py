"""Cron expression evaluation for the offline scheduler.

Wraps the third-party ``croniter`` library so the scheduler service has one
place to translate ``cron_expr + timezone + reference time`` into the next
firing instant. Using a real cron parser avoids the kind of off-by-one
mistakes a hand-rolled parser would make.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from croniter import croniter


def _coerce_now(now: Optional[datetime], tz: str) -> datetime:
    zone = ZoneInfo(tz) if tz else ZoneInfo("UTC")
    if now is None:
        now = datetime.now(tz=zone)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=zone)
    return now.astimezone(zone)


def next_fire(cron_expr: str, *, tz: str = "UTC",
              now: Optional[datetime] = None) -> datetime:
    """Return the next time after ``now`` at which ``cron_expr`` fires.

    The returned datetime is timezone-aware in UTC so it is safe to compare
    against Django's ``timezone.now()`` regardless of the schedule's local
    timezone.
    """
    base = _coerce_now(now, tz)
    itr = croniter(cron_expr, base)
    nxt = itr.get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=ZoneInfo(tz) if tz else timezone.utc)
    return nxt.astimezone(timezone.utc)


def is_valid(cron_expr: str) -> bool:
    return croniter.is_valid(cron_expr)
