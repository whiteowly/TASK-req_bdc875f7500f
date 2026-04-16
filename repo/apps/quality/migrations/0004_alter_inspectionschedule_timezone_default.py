"""Align InspectionSchedule.timezone migration default with model callable.

The model now uses ``_default_timezone()`` (reads ``settings.TIME_ZONE``)
rather than the hardcoded ``'UTC'`` that was in the initial migration.
Django cannot serialize an arbitrary callable into a migration file, so we
reference the same function the model uses.  For databases already deployed,
existing rows keep their stored timezone value; only *new* rows created
after this migration pick up the application-configured default.
"""
import apps.quality.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("quality", "0003_inspectionruleresult_snapshot_data"),
    ]

    operations = [
        migrations.AlterField(
            model_name="inspectionschedule",
            name="timezone",
            field=models.CharField(
                default=apps.quality.models._default_timezone,
                max_length=64,
            ),
        ),
    ]
