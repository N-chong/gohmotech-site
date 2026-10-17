"""
Celery Configuration for KaMoTech

This module configures Celery for background task processing:
- Automated feeding schedules
- ML model inference (batch processing)
- Data aggregation and cleanup
- Alert notifications
"""

import os
from celery import Celery
from celery.schedules import crontab

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Create Celery app
app = Celery('goat_monitoring')

# Load configuration from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all installed apps
app.autodiscover_tasks()

# Periodic task schedule (Celery Beat)
app.conf.beat_schedule = {
    'ensure-live-detection': {
        'task': 'ml_models.tasks.ensure_live_detection',
        'schedule': 15.0,
    },
    # Check time-based schedules every minute
    'check-automation-schedules': {
        'task': 'iot.tasks.check_and_execute_schedules',
        'schedule': 60.0,  # Every 60 seconds
    },
    
    # Check sensor-based automation rules every 30 seconds
    'check-automation-rules': {
        'task': 'iot.tasks.check_and_execute_rules',
        'schedule': 30.0,  # Every 30 seconds
    },
    
    # Execute scheduled feeding every minute
    'execute-scheduled-feeding': {
        'task': 'iot.tasks.execute_scheduled_feeding',
        'schedule': 60.0,  # Every 60 seconds
    },
    
    # Check feeding schedules every minute (legacy support)
    'check-feeding-schedules': {
        'task': 'feeding.tasks.check_feeding_schedules',
        'schedule': 60.0,  # Every 60 seconds
    },
    
    # Finalize completed Manila-aligned 30-minute sensor periods. Running every
    # five minutes also picks up late arrivals without delaying live alerts.
    'aggregate-sensor-data': {
        'task': 'iot.tasks.aggregate_sensor_data',
        'schedule': 300.0,  # Every 5 minutes
    },

    # Guarded raw cleanup. The task remains a no-op until an administrator
    # enables cleanup after verifying historical summaries.
    'cleanup-old-sensor-data': {
        'task': 'iot.tasks.cleanup_old_sensor_data',
        'schedule': crontab(hour=2, minute=30),
    },

    # Evaluate configured environmental thresholds and 30-second sensor health.
    'check-monitoring-alerts': {
        'task': 'iot.tasks.check_monitoring_alerts',
        'schedule': 60.0,
    },
    
    # Cleanup old detections daily at 2 AM
    'cleanup-old-detections': {
        'task': 'ml_models.tasks.cleanup_old_detections',
        'schedule': crontab(hour=2, minute=0),
    },
    
    # Check for low feed levels every hour
    'check-low-feed-levels': {
        'task': 'feeding.tasks.check_low_feed_levels',
        'schedule': 3600.0,  # Every hour
    },
    
    # AI-Powered Smart Door Check at 7:30 PM daily
    'ai-scheduled-door-check': {
        'task': 'iot.tasks.scheduled_door_check',
        'schedule': crontab(hour=19, minute=30),  # 7:30 PM
    },
    
    # Check for missing goats every 2 hours
    'check-missing-goats-periodic': {
        'task': 'iot.tasks.check_missing_goats_periodic',
        'schedule': 7200.0,  # Every 2 hours
    },

    # Send the daily SMS summary at the operator's configured time
    'sms-daily-summary': {
        'task': 'sms.tasks.send_daily_summary',
        'schedule': 60.0,  # Every 60 seconds; task self-gates on daily_time
    },

    # Fire due SMS reminders every minute (mirrors scheduled feeding)
    'sms-due-reminders': {
        'task': 'sms.tasks.send_due_reminders',
        'schedule': 60.0,  # Every 60 seconds
    },
}

# Celery configuration
# NOTE: Don't override broker/backend here - let it load from Django settings
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Manila',  # Match Django timezone
    enable_utc=False,  # Use local time
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    # RF-DETR leaves native allocator pages resident after its session. Recycle
    # that worker child once the task has ended, not while inference is active.
    worker_max_memory_per_child=1_000_000,  # KiB (about 1 GiB)
)
