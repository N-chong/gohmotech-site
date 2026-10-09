from django.db import migrations, models


def enforce_thirty_minute_minimum(apps, schema_editor):
    settings_model = apps.get_model("iot", "EnvironmentalAlertSettings")
    settings_model.objects.filter(stale_after_seconds__lt=1800).update(
        stale_after_seconds=1800
    )


class Migration(migrations.Migration):

    dependencies = [
        ("iot", "0024_sensor_cleanup_indexes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="environmentalalertsettings",
            name="stale_after_seconds",
            field=models.PositiveIntegerField(
                default=1800,
                help_text=(
                    "Minimum 1800 seconds (30 minutes) without data before "
                    "a stale alert."
                ),
            ),
        ),
        migrations.RunPython(
            enforce_thirty_minute_minimum,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
