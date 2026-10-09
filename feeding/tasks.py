"""
Celery tasks for Feeding System

Background tasks for:
- Automated feeding based on schedules
- Feed level monitoring and alerts
- Feed log aggregation
"""

from celery import shared_task
from django.utils import timezone
from django.db.models import F
import logging

logger = logging.getLogger(__name__)


@shared_task
def check_feeding_schedules():
    """
    Check and execute feeding schedules.
    This task runs every minute to check if any feeding should occur.
    """
    from .models import FeedSchedule
    
    now = timezone.now()
    current_time = now.time()
    current_day = now.weekday()  # 0=Monday, 6=Sunday
    
    # Adjust to 0=Sunday format
    current_day_sunday = (current_day + 1) % 7
    
    # Get active schedules for current time (within 1 minute window)
    schedules = FeedSchedule.objects.filter(
        is_active=True,
        schedule_time__hour=current_time.hour,
        schedule_time__minute=current_time.minute
    )
    
    for schedule in schedules:
        # Check if today is in the schedule's days_of_week
        if current_day_sunday in schedule.days_of_week or len(schedule.days_of_week) == 0:
            # Execute feeding
            try:
                execute_feeding.delay(schedule.id)
                logger.info(f"Scheduled feeding triggered for {schedule.feeder.name}")
            except Exception as e:
                logger.error(f"Failed to trigger feeding for {schedule.feeder.name}: {e}")


@shared_task
def execute_feeding(schedule_id):
    """
    Execute a feeding operation.
    
    Args:
        schedule_id: ID of the FeedSchedule to execute
    """
    from .models import FeedSchedule, FeedLog, FeedLevel
    
    try:
        schedule = FeedSchedule.objects.get(id=schedule_id)
        feeder = schedule.feeder
        amount = schedule.amount_grams
        
        # Check if there's enough feed
        try:
            feed_level = FeedLevel.objects.get(feeder=feeder)
            if feed_level.current_level_grams < amount:
                # Not enough feed
                FeedLog.objects.create(
                    feeder=feeder,
                    amount_dispensed=0,
                    scheduled=True,
                    schedule=schedule,
                    status='failed',
                    error_message=f'Insufficient feed. Available: {feed_level.current_level_grams}g, Required: {amount}g'
                )
                logger.warning(f"Feeding failed: Insufficient feed in {feeder.name}")
                return
        except FeedLevel.DoesNotExist:
            logger.warning(f"No feed level record for {feeder.name}")
        
        # TODO: Send MQTT command to actual feeder device
        # mqtt_client.publish(f"feeders/{feeder.device_id}/feed", amount)
        
        # Create feed log
        FeedLog.objects.create(
            feeder=feeder,
            amount_dispensed=amount,
            scheduled=True,
            schedule=schedule,
            status='success'
        )
        
        # Update feed level
        try:
            feed_level = FeedLevel.objects.get(feeder=feeder)
            feed_level.current_level_grams = max(0, feed_level.current_level_grams - amount)
            feed_level.save()
        except FeedLevel.DoesNotExist:
            pass
        
        logger.info(f"Feeding executed successfully: {feeder.name}, {amount}g")
        
    except FeedSchedule.DoesNotExist:
        logger.error(f"FeedSchedule {schedule_id} not found")
    except Exception as e:
        logger.error(f"Error executing feeding: {e}")


@shared_task
def check_low_feed_levels():
    """
    Check for feeders with low feed levels and create alerts.
    """
    from .models import FeedLevel
    from iot.models import Alert
    
    all_levels = FeedLevel.objects.select_related('feeder').all()
    low_feeders = all_levels.filter(current_level_grams__lt=F('low_level_threshold'))
    
    for feed_level in low_feeders:
        # Check if there's already an unresolved alert
        existing_alert = Alert.objects.filter(
            device=feed_level.feeder,
            deduplication_key=f'feed-low:{feed_level.feeder_id}',
            is_resolved=False
        ).exists()
        
        if not existing_alert:
            Alert.objects.create(
                device=feed_level.feeder,
                severity='high',
                alert_kind='feed_low',
                deduplication_key=f'feed-low:{feed_level.feeder_id}',
                message=f'Low feed level: {feed_level.current_level_grams}g remaining (threshold: {feed_level.low_level_threshold}g)'
            )
            logger.warning(f"Low feed alert created for {feed_level.feeder.name}")

    # Recovery closes the current condition. A later low reading can therefore
    # create a fresh alert, while a continuously-low feeder remains deduplicated.
    normal_feeders = all_levels.filter(current_level_grams__gte=F('low_level_threshold'))
    for feed_level in normal_feeders:
        open_alerts = Alert.objects.filter(
            device=feed_level.feeder,
            deduplication_key=f'feed-low:{feed_level.feeder_id}',
            is_resolved=False,
        )
        for alert in open_alerts:
            alert.is_resolved = True
            alert.resolved_at = timezone.now()
            alert.save(update_fields=['is_resolved', 'resolved_at'])
    
    return f"Checked {low_feeders.count()} feeders with low levels"
