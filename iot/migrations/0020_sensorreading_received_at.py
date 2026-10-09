from django.db import migrations, models
from django.db.models import F
import django.utils.timezone


def preserve_existing_arrival_times(apps, schema_editor):
    SensorReading = apps.get_model("iot", "SensorReading")
    # Exact historical arrival times were not previously retained. Using the
    # existing authoritative timestamp avoids changing or reinterpreting any
    # historical instant and gives old rows a consistent value.
    SensorReading.objects.update(received_at=F("timestamp"))


class Migration(migrations.Migration):
    dependencies = [("iot", "0019_standard_goat_photo_angles")]

    operations = [
        migrations.AddField(
            model_name="sensorreading",
            name="received_at",
            field=models.DateTimeField(
                db_index=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
        ),
        migrations.RunPython(preserve_existing_arrival_times, migrations.RunPython.noop),
    ]
