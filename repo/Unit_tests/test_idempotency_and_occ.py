"""Idempotency window + optimistic concurrency unit coverage."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.platform_common import idempotency as idem
from apps.platform_common.concurrency import check_version, parse_if_match
from apps.platform_common.errors import (
    IdempotencyKeyConflict,
    ValidationFailure,
    VersionConflict,
)
from apps.platform_common.models import IdempotencyKey


def test_store_and_lookup_returns_existing(db):
    idem.store(
        key="k1", actor_user_id="usr_a", method="POST", path="/x",
        request_hash="abc", response_status=201, response_body={"ok": True},
    )
    found = idem.lookup(key="k1", actor_user_id="usr_a", method="POST", path="/x")
    assert found is not None
    assert found.response_body == {"ok": True}


def test_same_key_different_payload_raises_conflict(db):
    idem.store(
        key="k2", actor_user_id="usr_a", method="POST", path="/y",
        request_hash="hashA", response_status=201, response_body={"ok": True},
    )
    with pytest.raises(IdempotencyKeyConflict):
        idem.store(
            key="k2", actor_user_id="usr_a", method="POST", path="/y",
            request_hash="hashB", response_status=201, response_body={"ok": True},
        )


def test_expired_keys_dont_dedupe(db):
    rec = idem.store(
        key="k3", actor_user_id="usr_a", method="POST", path="/z",
        request_hash="abc", response_status=201, response_body={},
    )
    # Force expiry
    IdempotencyKey.objects.filter(pk=rec.pk).update(expires_at=timezone.now() - timedelta(seconds=5))
    found = idem.lookup(key="k3", actor_user_id="usr_a", method="POST", path="/z")
    assert found is None


def test_parse_if_match_accepts_quoted_and_unquoted():
    assert parse_if_match('"7"') == 7
    assert parse_if_match("3") == 3


def test_parse_if_match_missing_raises_validation():
    with pytest.raises(ValidationFailure):
        parse_if_match(None)


def test_check_version_mismatch_raises():
    with pytest.raises(VersionConflict):
        check_version(current=2, expected=1)


def test_check_version_match_ok():
    check_version(current=4, expected=4)
