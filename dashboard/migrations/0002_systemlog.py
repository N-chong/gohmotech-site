from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("level", models.CharField(choices=[("info", "Info"), ("warning", "Warning"), ("error", "Error"), ("critical", "Critical")], db_index=True, default="info", max_length=10)),
                ("category", models.CharField(choices=[("auth", "Authentication"), ("request", "Request"), ("security", "Security"), ("system", "System"), ("task", "Background task"), ("device", "Device"), ("data", "Data change")], db_index=True, default="system", max_length=20)),
                ("event", models.CharField(db_index=True, max_length=100)),
                ("message", models.TextField()),
                ("source", models.CharField(blank=True, db_index=True, max_length=150)),
                ("actor_label", models.CharField(blank=True, max_length=150)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("request_method", models.CharField(blank=True, max_length=10)),
                ("path", models.CharField(blank=True, max_length=500)),
                ("status_code", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="system_log_entries", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddIndex(model_name="systemlog", index=models.Index(fields=["category", "-created_at"], name="syslog_category_date_idx")),
        migrations.AddIndex(model_name="systemlog", index=models.Index(fields=["level", "-created_at"], name="syslog_level_date_idx")),
        migrations.AddIndex(model_name="systemlog", index=models.Index(fields=["actor", "-created_at"], name="syslog_actor_date_idx")),
    ]
