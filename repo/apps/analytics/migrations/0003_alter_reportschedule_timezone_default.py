"""Align ReportSchedule.timezone migration default with model callable.

Same rationale as the quality schedule migration — the model now uses
``_default_timezone()`` (reads ``settings.TIME_ZONE``) rather than the
hardcoded ``'UTC'``.  Existing rows are unaffected; only new rows pick up
the application-configured default.
"""
import apps.analytics.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0002_reportschedule"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reportschedule",
            name="timezone",
            field=models.CharField(
                default=apps.analytics.models._default_timezone,
                max_length=64,
            ),
        ),
    ]
