import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('sms', '0002_smsregistration')]

    operations = [
        migrations.AlterField(
            model_name='smslog',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'), ('sending', 'Sending'),
                    ('sent', 'Sent'), ('failed', 'Failed'),
                ],
                db_index=True, default='pending', max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='DailySummaryRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('scheduled_date', models.DateField(unique=True)),
                ('scheduled_for', models.DateTimeField(db_index=True)),
                ('executed_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'), ('processing', 'Processing'),
                        ('sent', 'Sent'), ('failed', 'Failed'),
                        ('skipped', 'Skipped'),
                    ], db_index=True, default='pending', max_length=20)),
                ('recipient', models.CharField(blank=True, max_length=20)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('sms_log', models.OneToOneField(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='daily_summary_run', to='sms.smslog')),
            ],
            options={'ordering': ['-scheduled_date']},
        ),
    ]
