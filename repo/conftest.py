"""Top-level pytest fixtures.

This module DOES NOT introduce any mock/fake/stub substitutions. It only
enables the standard pytest-django database access and provides convenience
helpers for creating real users/sessions in MySQL during tests.
"""
from __future__ import annotations

import os
import secrets

import pytest
from rest_framework.test import APIClient


def pytest_configure(config):  # type: ignore[no-untyped-def]
    config.addinivalue_line(
        "markers",
        "no_db: skip the autouse pytest-django db fixture (for tests that don't need MySQL)",
    )


@pytest.fixture(autouse=True)
def _enable_db_access(request):  # type: ignore[no-untyped-def]
    """Most tests need real DB access; tests marked ``no_db`` opt out so they
    can run without a MySQL connection (e.g. config and TLS unit tests)."""
    if request.node.get_closest_marker("no_db"):
        yield
        return
    request.getfixturevalue("db")
    yield


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def _make_user(username: str, password: str, roles=()):
    from apps.identity.services import (
        assign_roles,
        create_user,
        ensure_seed_roles,
        login,
    )

    ensure_seed_roles()
    user = create_user(username=username, password=password, roles=roles)
    return user


@pytest.fixture
def make_user():
    """Factory to create real users + (optional) role assignments in MySQL."""
    return _make_user


@pytest.fixture
def authed_client(api_client, db):
    """Build an authenticated APIClient for a user with the given roles."""
    from apps.identity.services import login

    def _build(roles=("administrator",), username=None, password=None):
        username = username or f"u_{secrets.token_hex(4)}"
        password = password or "TestPass!1234"
        _make_user(username, password, roles=roles)
        _, token = login(username=username, password=password)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client, token, username

    return _build
