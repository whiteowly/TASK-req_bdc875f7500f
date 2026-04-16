"""Create the initial administrator account for a fresh deployment.

Idempotent: refuses to run if any administrator user already exists,
unless ``--force`` is passed (with a visible warning). Designed for
first-boot only — operators should use the admin API after the first
account is live.

Usage:
    python manage.py bootstrap_admin --username admin --password <secret>
"""
from django.core.management.base import BaseCommand, CommandError

from apps.identity.models import User
from apps.identity.services import assign_roles, create_user, ensure_seed_roles


class Command(BaseCommand):
    help = "Create the initial administrator account on a fresh deployment."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow creation even when administrators already exist (use with caution).",
        )

    def handle(self, *args, **options):
        ensure_seed_roles()
        existing_admins = (
            User.objects.filter(
                is_active=True,
                user_roles__role__name="administrator",
            ).distinct().count()
        )
        if existing_admins > 0 and not options["force"]:
            raise CommandError(
                f"{existing_admins} active administrator(s) already exist. "
                "Use --force to create another (this is intended for recovery, "
                "not routine operation)."
            )
        if existing_admins > 0 and options["force"]:
            self.stderr.write(self.style.WARNING(
                f"WARNING: {existing_admins} administrator(s) already exist. "
                "Creating an additional one because --force was supplied."
            ))
        username = options["username"].strip()
        password = options["password"]
        if len(password) < 12:
            raise CommandError("--password must be at least 12 characters.")
        try:
            user = create_user(username=username, password=password, roles=["administrator"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"administrator '{username}' created (id={user.id})"
        ))
