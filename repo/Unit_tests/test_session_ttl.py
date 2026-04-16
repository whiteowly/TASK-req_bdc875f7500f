"""8-hour session TTL + revoke semantics."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.identity import services
from apps.identity.models import Session


def test_login_session_expires_in_8_hours(db):
    services.ensure_seed_roles()
    services.create_user(username="alice", password="StrongPass!1234")
    session, token = services.login(username="alice", password="StrongPass!1234")
    delta = session.expires_at - timezone.now()
    assert settings.SESSION_TTL_SECONDS == 8 * 3600
    assert delta > timedelta(hours=7, minutes=59)
    assert delta <= timedelta(hours=8)
    assert token


def test_revoke_marks_session(db):
    services.ensure_seed_roles()
    services.create_user(username="bob", password="StrongPass!1234")
    session, _ = services.login(username="bob", password="StrongPass!1234")
    services.revoke_session(session)
    session.refresh_from_db()
    assert session.revoked_at is not None
    assert session.is_revoked() is True


def test_expired_session_reports_expired(db):
    services.ensure_seed_roles()
    services.create_user(username="carol", password="StrongPass!1234")
    session, _ = services.login(username="carol", password="StrongPass!1234")
    Session.objects.filter(pk=session.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    session.refresh_from_db()
    assert session.is_expired() is True
