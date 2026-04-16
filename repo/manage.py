#!/usr/bin/env python
"""Django management entry point."""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "governanceiq.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - import diagnostic
        raise ImportError(
            "Could not import Django. Make sure it is installed and available on PYTHONPATH."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
