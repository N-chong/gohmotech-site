from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(
        name="OnboardingProgress",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("has_completed_tutorial", models.BooleanField(default=False)),
            ("completed_at", models.DateTimeField(blank=True, null=True)),
            ("completion_reason", models.CharField(blank=True, choices=[("finished", "Finished"), ("skipped", "Skipped")], max_length=10)),
            ("role", models.CharField(max_length=20)),
            ("step", models.PositiveSmallIntegerField(default=0)),
            ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="onboarding_progress", to=settings.AUTH_USER_MODEL)),
        ],
    )]
