"""Run a single scheduler tick: fire any due inspection/report schedules."""
import json

from django.core.management.base import BaseCommand

from apps.platform_common.scheduler import tick_all


class Command(BaseCommand):
    help = (
        "Process every active schedule whose next_run_at <= now: trigger the "
        "associated work and advance next_run_at."
    )

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true",
                            help="Emit the tick result as JSON on stdout.")

    def handle(self, *args, **options):
        result = tick_all()
        if options["json"]:
            self.stdout.write(json.dumps(result))
            return
        n_ins = len(result["inspections"])
        n_rep = len(result["reports"])
        self.stdout.write(self.style.SUCCESS(
            f"scheduler tick: fired {n_ins} inspection schedule(s) and "
            f"{n_rep} report schedule(s)"
        ))
        for entry in result["inspections"]:
            self.stdout.write(
                f"  inspection schedule={entry['schedule_id']} "
                f"dataset={entry['dataset_id']} "
                f"run={entry['inspection_run_id']} "
                f"next_run_at={entry['next_run_at']}"
            )
        for entry in result["reports"]:
            self.stdout.write(
                f"  report schedule={entry['schedule_id']} "
                f"definition={entry['report_definition_id']} "
                f"run={entry['report_run_id']} rows={entry['rows']} "
                f"next_run_at={entry['next_run_at']}"
            )
