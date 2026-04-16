"""bootstrap_admin management command tests."""
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.identity.models import User


def test_creates_first_admin(db):
    out = StringIO()
    call_command("bootstrap_admin", "--username", "superadmin",
                 "--password", "VeryStrongPass!1", stdout=out)
    assert "superadmin" in out.getvalue()
    u = User.objects.get(username="superadmin")
    assert u.user_roles.filter(role__name="administrator").exists()


def test_refuses_second_admin_without_force(db):
    call_command("bootstrap_admin", "--username", "first",
                 "--password", "VeryStrongPass!1", stdout=StringIO())
    with pytest.raises(CommandError, match="already exist"):
        call_command("bootstrap_admin", "--username", "second",
                     "--password", "VeryStrongPass!1", stdout=StringIO())


def test_allows_second_with_force(db):
    call_command("bootstrap_admin", "--username", "first",
                 "--password", "VeryStrongPass!1", stdout=StringIO())
    out = StringIO()
    call_command("bootstrap_admin", "--username", "second",
                 "--password", "VeryStrongPass!1", "--force", stdout=out)
    assert "second" in out.getvalue()
    assert User.objects.filter(user_roles__role__name="administrator").distinct().count() == 2


def test_rejects_short_password(db):
    with pytest.raises(CommandError, match="12 characters"):
        call_command("bootstrap_admin", "--username", "x",
                     "--password", "short", stdout=StringIO())


def test_idempotent_on_existing_username(db):
    call_command("bootstrap_admin", "--username", "admin",
                 "--password", "VeryStrongPass!1", stdout=StringIO())
    with pytest.raises(CommandError, match="already exist"):
        call_command("bootstrap_admin", "--username", "admin",
                     "--password", "VeryStrongPass!1", stdout=StringIO())
