"""Idempotently seed the canonical role rows."""
from django.core.management.base import BaseCommand

from apps.identity.services import ensure_seed_roles


class Command(BaseCommand):
    help = "Ensure 'administrator', 'operations', and 'user' roles exist."

    def handle(self, *args, **options) -> None:
        ensure_seed_roles()
        self.stdout.write(self.style.SUCCESS("roles seeded"))
