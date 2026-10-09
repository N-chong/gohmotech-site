import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('iot', '0020_sensorreading_received_at')]

    operations = [
        migrations.AddField(
            model_name='alert', name='alert_kind',
            field=models.CharField(blank=True, db_index=True, max_length=40,
                                   help_text='Stable machine-readable category such as sensor_stale or temperature_high'),
        ),
        migrations.AddField(
            model_name='alert', name='deduplication_key',
            field=models.CharField(blank=True, db_index=True, max_length=255,
                                   help_text='Key used to keep one unresolved alert per ongoing condition'),
        ),
        migrations.CreateModel(
            name='EnvironmentalAlertSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(default=True)),
                ('temperature_min_c', models.FloatField(blank=True, null=True)),
                ('temperature_max_c', models.FloatField(blank=True, null=True)),
                ('humidity_min_percent', models.FloatField(
                    blank=True, null=True,
                    validators=[django.core.validators.MinValueValidator(0),
                                django.core.validators.MaxValueValidator(100)])),
                ('humidity_max_percent', models.FloatField(
                    blank=True, null=True,
                    validators=[django.core.validators.MinValueValidator(0),
                                django.core.validators.MaxValueValidator(100)])),
                ('stale_detection_enabled', models.BooleanField(default=True)),
                ('stale_after_seconds', models.PositiveIntegerField(
                    default=90,
                    help_text='Firmware reports every 30 seconds; 90 seconds allows three missed reports.')),
                ('threshold_severity', models.CharField(
                    choices=[('low', 'Low'), ('medium', 'Medium'),
                             ('high', 'High'), ('critical', 'Critical')],
                    default='high', max_length=20)),
                ('stale_severity', models.CharField(
                    choices=[('low', 'Low'), ('medium', 'Medium'),
                             ('high', 'High'), ('critical', 'Critical')],
                    default='high', max_length=20)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Environmental Alert Settings',
                'verbose_name_plural': 'Environmental Alert Settings',
            },
        ),
    ]
