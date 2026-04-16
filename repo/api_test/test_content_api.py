"""Content entries (poetry/tribute) + version/publish/rollback API tests."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.content.models import ContentVersion


def _entry(client, ctype="poetry", slug="alpha"):
    res = client.post(
        "/api/v1/content/entries",
        {"content_type": ctype, "slug": slug, "title": slug.title()},
        format="json",
    )
    assert res.status_code == 201, res.content
    return res.json()


def _add_version(client, entry_id, body="hello world"):
    res = client.post(
        f"/api/v1/content/entries/{entry_id}/versions",
        {"body": body},
        format="json",
    )
    assert res.status_code == 201
    return res.json()


def test_create_entry_both_content_types(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    p = _entry(client, "poetry", "spring")
    t = _entry(client, "tribute", "in-memory")
    assert p["content_type"] == "poetry"
    assert t["content_type"] == "tribute"


def test_invalid_content_type_rejected(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    res = client.post("/api/v1/content/entries",
                      {"content_type": "essay", "slug": "x", "title": "X"}, format="json")
    assert res.status_code == 400


def test_user_role_only_sees_published(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    e = _entry(ops, "poetry", "limited")
    v = _add_version(ops, e["id"])
    # User cannot see entry while it has no published version
    user_client, _, _ = authed_client(roles=("user",))
    listing = user_client.get("/api/v1/content/entries").json()
    assert all(item["id"] != e["id"] for item in listing["entries"])
    # Publish via ops
    pub = ops.post(
        f"/api/v1/content/entries/{e['id']}/publish",
        {"version_id": v["id"], "reason": "first publish text now"},
        format="json", HTTP_IF_MATCH='"1"',
    )
    assert pub.status_code == 200
    # User now sees it
    listing2 = user_client.get("/api/v1/content/entries").json()
    assert any(item["id"] == e["id"] for item in listing2["entries"])


def test_publish_rejects_short_reason(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    e = _entry(client, "poetry", "shortreason")
    v = _add_version(client, e["id"])
    res = client.post(
        f"/api/v1/content/entries/{e['id']}/publish",
        {"version_id": v["id"], "reason": "too short"},
        format="json", HTTP_IF_MATCH='"1"',
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "publish_reason_too_short"


def test_publish_unauthorized_for_user(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    e = _entry(ops, "poetry", "noprivs")
    v = _add_version(ops, e["id"])
    user_client, _, _ = authed_client(roles=("user",))
    res = user_client.post(
        f"/api/v1/content/entries/{e['id']}/publish",
        {"version_id": v["id"], "reason": "trying as user role"},
        format="json", HTTP_IF_MATCH='"1"',
    )
    assert res.status_code == 403


def test_only_one_published_version(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    e = _entry(client, "poetry", "single_pub")
    v1 = _add_version(client, e["id"], "v1")
    v2 = _add_version(client, e["id"], "v2")
    pub1 = client.post(
        f"/api/v1/content/entries/{e['id']}/publish",
        {"version_id": v1["id"], "reason": "initial publish text"},
        format="json", HTTP_IF_MATCH='"1"',
    )
    assert pub1.status_code == 200
    pub2 = client.post(
        f"/api/v1/content/entries/{e['id']}/publish",
        {"version_id": v2["id"], "reason": "second publish supersedes"},
        format="json", HTTP_IF_MATCH='"2"',
    )
    assert pub2.status_code == 200
    published_count = ContentVersion.objects.filter(entry_id=e["id"], state="published").count()
    assert published_count == 1


def test_rollback_outside_window_returns_422(authed_client, db):
    client, _, _ = authed_client(roles=("operations",))
    e = _entry(client, "tribute", "rollback_test")
    v = _add_version(client, e["id"], "old")
    pub = client.post(
        f"/api/v1/content/entries/{e['id']}/publish",
        {"version_id": v["id"], "reason": "initial publish text"},
        format="json", HTTP_IF_MATCH='"1"',
    )
    assert pub.status_code == 200
    # Force the source version older than 30 days
    ContentVersion.objects.filter(pk=v["id"]).update(
        created_at=timezone.now() - timedelta(days=31)
    )
    res = client.post(
        f"/api/v1/content/entries/{e['id']}/rollback",
        {"target_version_id": v["id"], "reason": "rollback to older content"},
        format="json", HTTP_IF_MATCH='"2"',
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "rollback_window_exceeded"


def test_diff_endpoint(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    e = _entry(client, "poetry", "diffable")
    a = _add_version(client, e["id"], "alpha body")
    b = _add_version(client, e["id"], "beta body")
    res = client.get(
        f"/api/v1/content/entries/{e['id']}/diff?from_version_id={a['id']}&to_version_id={b['id']}"
    )
    assert res.status_code == 200
    assert "body" in res.json()["changed_fields"]


def test_xss_payload_is_escaped_on_persist(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    e = _entry(client, "poetry", "xss_test")
    res = client.post(
        f"/api/v1/content/entries/{e['id']}/versions",
        {"body": "<script>alert(1)</script>"},
        format="json",
    )
    assert "&lt;script&gt;" in res.json()["body"]
    assert "<script>" not in res.json()["body"]
