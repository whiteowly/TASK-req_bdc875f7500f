from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0002_inspectionschedule_last_enqueued_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='inspectionruleresult',
            name='snapshot_data',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
