from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sms", "0003_daily_summary_run"),
    ]

    operations = [
        migrations.AddField(
            model_name="smsregistration",
            name="receives_farm_alerts",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Administrator-managed permission to receive farm alert SMS. "
                    "Account owners cannot enable this themselves."
                ),
            ),
        ),
    ]
