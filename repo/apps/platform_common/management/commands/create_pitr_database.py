"""Create the target database for PITR restores.

This management command creates the target database (default ``gi_pitr``)
inside the MySQL instance using the root credentials from runtime secrets,
avoiding the need for operators to run raw ``mysql -e`` shell commands.
"""
import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the target database for point-in-time recovery restores."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database-name",
            default="gi_pitr",
            help="Name of the database to create (default: gi_pitr).",
        )

    def handle(self, *args, **options):
        import MySQLdb

        db_name = options["database_name"]
        # Validate the name to prevent injection (alphanumeric + underscore only).
        if not db_name.replace("_", "").isalnum():
            raise CommandError(
                f"Invalid database name: {db_name!r}. "
                "Only alphanumeric characters and underscores are allowed."
            )

        root_password = ""
        pw_file = os.environ.get(
            "MYSQL_ROOT_PASSWORD_FILE",
            "/run/runtime-secrets/mysql_root_password",
        )
        try:
            with open(pw_file) as f:
                root_password = f.read().strip()
        except FileNotFoundError:
            root_password = os.environ.get("MYSQL_ROOT_PASSWORD", "")
        if not root_password:
            raise CommandError(
                "Cannot read MySQL root password from "
                f"{pw_file} or MYSQL_ROOT_PASSWORD env var."
            )

        host = os.environ.get("MYSQL_HOST", "db")
        port = int(os.environ.get("MYSQL_PORT", "3306"))

        conn = MySQLdb.connect(
            host=host, port=port, user="root", passwd=root_password,
        )
        try:
            cur = conn.cursor()
            # Use backticks around the name; we already validated it above.
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            conn.commit()
            self.stdout.write(self.style.SUCCESS(
                f"Database '{db_name}' is ready."
            ))
        finally:
            conn.close()
