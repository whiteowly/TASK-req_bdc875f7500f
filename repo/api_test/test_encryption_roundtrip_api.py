"""API tests proving encryption roundtrip: ciphertext at rest, plaintext in responses.

These tests exercise the full HTTP path — create content via API, verify the
response contains plaintext, and verify the DB column contains ciphertext.
"""
from __future__ import annotations

import pytest
from django.db import connection


def test_content_body_encrypted_at_rest_roundtrip(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    # Create entry
    entry_res = client.post(
        "/api/v1/content/entries",
        {"content_type": "poetry", "slug": "enc_api_test", "title": "Enc API"},
        format="json",
    )
    assert entry_res.status_code == 201
    entry_id = entry_res.json()["id"]

    # Add version with sensitive body
    ver_res = client.post(
        f"/api/v1/content/entries/{entry_id}/versions",
        {"body": "sensitive poem content"},
        format="json",
    )
    assert ver_res.status_code == 201
    ver_data = ver_res.json()
    version_id = ver_data["id"]

    # API response returns decrypted plaintext (HTML-escaped by sanitize_body)
    assert "sensitive poem content" in ver_data["body"]

    # Raw DB contains ciphertext
    with connection.cursor() as cur:
        cur.execute("SELECT body FROM content_versions WHERE id = %s", [version_id])
        raw = cur.fetchone()[0]
    assert raw.startswith("v1."), f"Expected ciphertext, got: {raw[:40]}"
    assert "sensitive poem content" not in raw


def test_content_publish_roundtrip_with_encryption(authed_client):
    client, _, _ = authed_client(roles=("operations",))
    entry_res = client.post(
        "/api/v1/content/entries",
        {"content_type": "tribute", "slug": "enc_pub", "title": "Enc Pub"},
        format="json",
    )
    entry_id = entry_res.json()["id"]

    ver_res = client.post(
        f"/api/v1/content/entries/{entry_id}/versions",
        {"body": "tribute body text here"},
        format="json",
    )
    version_id = ver_res.json()["id"]

    pub_res = client.post(
        f"/api/v1/content/entries/{entry_id}/publish",
        {"version_id": version_id, "reason": "publishing encrypted content now"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert pub_res.status_code == 200
    pub_data = pub_res.json()
    assert "tribute body text here" in pub_data["version"]["body"]


def test_metadata_owner_encrypted_at_rest_via_api(authed_client):
    client, _, _ = authed_client(roles=("administrator",))
    # Create dataset
    ds_res = client.post(
        "/api/v1/datasets",
        {"code": "enc_md_api", "display_name": "Enc Metadata"},
        format="json",
    )
    assert ds_res.status_code == 201
    ds_id = ds_res.json()["id"]

    # Set metadata with owner
    md_res = client.patch(
        f"/api/v1/datasets/{ds_id}/metadata",
        {"owner": "secret_owner@edu", "retention_class": "standard", "sensitivity_level": "high"},
        format="json",
    )
    assert md_res.status_code == 200
    assert md_res.json()["owner"] == "secret_owner@edu"

    # Verify raw DB has ciphertext
    with connection.cursor() as cur:
        cur.execute(
            "SELECT owner FROM dataset_metadata WHERE dataset_id = %s", [ds_id]
        )
        raw = cur.fetchone()[0]
    assert raw.startswith("v1.")
    assert "secret_owner@edu" not in raw

    # Re-fetch via API — returns plaintext
    get_res = client.get(f"/api/v1/datasets/{ds_id}/metadata")
    assert get_res.status_code == 200
    assert get_res.json()["owner"] == "secret_owner@edu"
