"""Reusable encrypted model fields for sensitive data at rest.

Fields use the project's AES-256-GCM encryption helpers
(``DATA_ENCRYPTION_KEY`` / ``DATA_ENCRYPTION_KEY_ID``) so all sensitive
persisted data shares the same key-management path.

Usage::

    from apps.platform_common.fields import EncryptedTextField

    class MyModel(models.Model):
        secret_note = EncryptedTextField()
"""
from __future__ import annotations

from django.db import models

from .encryption import decrypt, encrypt


class EncryptedTextField(models.TextField):
    """A ``TextField`` that stores AES-256-GCM ciphertext in the database
    and returns decrypted plaintext to Python code.

    * ``from_db_value`` decrypts on read.
    * ``get_prep_value`` encrypts on write.
    * Legacy plaintext rows (not starting with ``v1.``) are returned as-is
      so the field is safe to deploy before a backfill migration.
    """

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        return encrypt(str(value))

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        if isinstance(value, str) and value.startswith("v1."):
            return decrypt(value)
        # Legacy plaintext — return as-is (graceful migration).
        return value

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Override the import path so Django migrations reference our field.
        path = "apps.platform_common.fields.EncryptedTextField"
        return name, path, args, kwargs
