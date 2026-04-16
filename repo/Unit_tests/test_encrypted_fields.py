"""Encrypted model fields — ciphertext stored in DB, plaintext returned to Python.

Tests prove:
- ContentVersion.body stores ciphertext at rest.
- DatasetMetadata.owner stores ciphertext at rest.
- Reads return decrypted plaintext transparently.
- The reusable EncryptedTextField works for roundtrips.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.catalog.models import Dataset, DatasetMetadata
from apps.content.models import ContentEntry, ContentVersion
from apps.platform_common.encryption import encrypt


# ---------------------------------------------------------------------------
# ContentVersion.body encryption
# ---------------------------------------------------------------------------

def test_content_version_body_stored_as_ciphertext(db):
    entry = ContentEntry.objects.create(
        content_type="poetry", slug="enc_test", title="Enc Test"
    )
    ver = ContentVersion.objects.create(
        entry=entry, body="my secret poem", state="draft"
    )
    # Read raw DB value via cursor — bypasses Django field decryption.
    with connection.cursor() as cur:
        cur.execute("SELECT body FROM content_versions WHERE id = %s", [ver.id])
        raw = cur.fetchone()[0]
    assert raw.startswith("v1."), f"Expected ciphertext envelope, got: {raw[:40]}"
    assert "my secret poem" not in raw


def test_content_version_body_decrypted_on_read(db):
    entry = ContentEntry.objects.create(
        content_type="tribute", slug="enc_read", title="Read Test"
    )
    ver = ContentVersion.objects.create(
        entry=entry, body="readable poem", state="draft"
    )
    ver.refresh_from_db()
    assert ver.body == "readable poem"


def test_content_version_empty_body_not_encrypted(db):
    entry = ContentEntry.objects.create(
        content_type="poetry", slug="enc_empty", title="Empty"
    )
    ver = ContentVersion.objects.create(
        entry=entry, body="", state="draft"
    )
    with connection.cursor() as cur:
        cur.execute("SELECT body FROM content_versions WHERE id = %s", [ver.id])
        raw = cur.fetchone()[0]
    assert raw == ""


# ---------------------------------------------------------------------------
# DatasetMetadata.owner encryption
# ---------------------------------------------------------------------------

def test_metadata_owner_stored_as_ciphertext(db):
    ds = Dataset.objects.create(code="enc_ds", display_name="Enc DS")
    md = DatasetMetadata.objects.create(
        dataset=ds, owner="alice@example.com",
        retention_class="standard", sensitivity_level="high",
    )
    with connection.cursor() as cur:
        cur.execute("SELECT owner FROM dataset_metadata WHERE id = %s", [md.id])
        raw = cur.fetchone()[0]
    assert raw.startswith("v1."), f"Expected ciphertext envelope, got: {raw[:40]}"
    assert "alice@example.com" not in raw


def test_metadata_owner_decrypted_on_read(db):
    ds = Dataset.objects.create(code="enc_ds_read", display_name="Read DS")
    md = DatasetMetadata.objects.create(
        dataset=ds, owner="bob@school.edu",
        retention_class="archive", sensitivity_level="medium",
    )
    md.refresh_from_db()
    assert md.owner == "bob@school.edu"


# ---------------------------------------------------------------------------
# Roundtrip consistency
# ---------------------------------------------------------------------------

def test_update_encrypted_field_roundtrip(db):
    entry = ContentEntry.objects.create(
        content_type="poetry", slug="enc_update", title="Update"
    )
    ver = ContentVersion.objects.create(entry=entry, body="original", state="draft")
    ver.body = "updated content"
    ver.save(update_fields=["body"])
    ver.refresh_from_db()
    assert ver.body == "updated content"
    # Confirm raw is ciphertext
    with connection.cursor() as cur:
        cur.execute("SELECT body FROM content_versions WHERE id = %s", [ver.id])
        raw = cur.fetchone()[0]
    assert raw.startswith("v1.")
    assert "updated content" not in raw
