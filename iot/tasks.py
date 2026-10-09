"""
Celery tasks for IoT System

Background tasks for:
- Sensor data aggregation
- Device health monitoring
- Alert notifications
- AI-powered smart door automation
"""

from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

# Map an actuator's desired STATE to a valid ActuationLog.action choice.
# Storing a raw state ('closed'/'on'/'off') as the action makes
# get_action_display() fall back to the raw string in the history feed. Only
# 'open' happens to also be a valid action, so the other three must be mapped.
STATE_TO_ACTION = {
    'open': 'open',
    'closed': 'close',
    'on': 'turn_on',
    'off': 'turn_off',
}

# Import AI tasks so they're registered with Celery
from .ai_tasks import (
    scheduled_door_check,
    check_missing_goats_periodic,
    start_realtime_detection,
    stop_realtime_detection
)

__all__ = [
    'scheduled_door_check', 'check_missing_goats_periodic',
    'start_realtime_detection', 'stop_realtime_detection',
]


@shared_task
def aggregate_sensor_data():
    """Persist completed 30-minute summaries and process bounded backlog."""
    from .sensor_storage import aggregate_due_periods

    results = aggregate_due_periods()
    summaries = sum(item['summaries'] for item in results)
    rows = sum(item['raw_rows'] for item in results)
    return f"Aggregated {summaries} streams from {rows} raw rows"


@shared_task
def check_monitoring_alerts():
    """Periodically detect stale sensors independent of any open browser."""
    from .monitoring import check_stale_sensors

    try:
        checked = check_stale_sensors()
        return f"Checked {checked} sensor device(s)"
    except Exception:
        logger.exception("[ALERT] Monitoring health check failed")
        return "Monitoring health check failed"


@shared_task
def check_device_health():
    """
    Check health status of all devices.
    Mark devices as inactive if they haven't sent data recently.
    """
    from .models import Device
    
    threshold = timezone.now() - timedelta(minutes=30)
    
    # Find devices that haven't sent data recently
    inactive_devices = Device.objects.filter(
        is_active=True,
        last_seen__lt=threshold
    )
    
    count = inactive_devices.count()
    inactive_devices.update(is_active=False)
    
    logger.info(f"Marked {count} devices as inactive")
    return f"Marked {count} devices as inactive"


@shared_task
def cleanup_old_sensor_data():
    """Apply the configured, aggregation-gated raw sensor retention policy."""
    from .sensor_storage import cleanup_aggregated_raw_data

    result = cleanup_aggregated_raw_data()
    if not result['enabled']:
        return "Raw sensor cleanup disabled pending summary verification"
    return (
        f"Deleted {result['deleted']} processed raw readings older than "
        f"{result['retention_days']} days"
    )


@shared_task
def send_alert_notification(alert_id):
    """
    Send notification for an alert.
    Can be email, SMS, push notification, etc.
    
    Args:
        alert_id: ID of the Alert to send
    """
    from .models import Alert
    
    try:
        alert = Alert.objects.get(id=alert_id)
        
        logger.info(f"Alert notification sent for {alert.id}")
        return f"Notification sent for alert {alert_id}"
        
    except Alert.DoesNotExist:
        logger.error(f"Alert {alert_id} not found")
        return f"Alert {alert_id} not found"


@shared_task
def check_and_execute_schedules():
    """
    Check and execute time-based automation schedules.
    Runs every minute via Celery Beat.
    """
    from .models import AutomationRule, ActuatorState
    from django.core.cache import cache
    
    # Check if automation is enabled
    if not cache.get('automation_enabled', True):
        logger.info("Automation is disabled - skipping schedule check")
        return "Automation disabled"
    
    # Use local time instead of UTC for schedule matching
    now = timezone.localtime(timezone.now())
    current_time = now.strftime('%H:%M')
    current_day = now.weekday()  # 0 = Monday, 6 = Sunday
    # Convert Django weekday to match our format (0 = Sunday)
    current_day_adjusted = (current_day + 1) % 7
    
    logger.info(f"Checking schedules at {current_time} (day {current_day_adjusted})")
    
    executed_count = 0
    
    # Get all active time-based schedules
    schedules = AutomationRule.objects.filter(
        is_active=True,
        rule_type='time_based'
    )
    
    for schedule in schedules:
        criteria = schedule.criteria
        schedule_time = criteria.get('time', '')
        days_of_week = criteria.get('days_of_week', [])
        
        # Check if schedule should run now
        if schedule_time == current_time:
            # Check if today is in the schedule
            if not days_of_week or current_day_adjusted in days_of_week:
                try:
                    # Execute the action
                    action = schedule.action
                    device = schedule.actuator
                    
                    # Map action to state
                    state_map = {
                        'open_door': 'open',
                        'close_door': 'closed',
                        'turn_on_light': 'on',
                        'turn_off_light': 'off'
                    }
                    
                    new_state = state_map.get(action, 'off')
                    
                    # Get device_type from criteria, or infer from action if not set
                    device_type = criteria.get('device_type')
                    if not device_type or device_type == 'unknown':
                        # Infer from action
                        if 'door' in action:
                            device_type = 'door'
                        elif 'light' in action:
                            device_type = 'light'
                        else:
                            device_type = 'door'  # Default fallback
                    
                    logger.info(f"Executing schedule: {schedule.name}, device_type={device_type}, action={action}, new_state={new_state}")
                    
                    # Update actuator state for the specific actuator type
                    actuator_state, created = ActuatorState.objects.get_or_create(
                        device=device,
                        actuator_type=device_type,
                        defaults={'current_state': new_state, 'mode': 'auto'}
                    )
                    
                    if not created:
                        actuator_state.current_state = new_state
                        actuator_state.mode = 'auto'
                        actuator_state.last_triggered_by = schedule.name
                        actuator_state.save()
                    
                    # Log the actuation
                    from .models import ActuationLog
                    ActuationLog.objects.create(
                        device=device,
                        action=STATE_TO_ACTION.get(new_state, 'turn_on'),
                        source='rule',
                        triggered_by=schedule.name
                    )
                    
                    executed_count += 1
                    logger.info(f"Executed schedule: {schedule.name} - {action}")
                    
                except Exception as e:
                    logger.error(f"Error executing schedule {schedule.name}: {str(e)}")
    
    logger.info(f"Checked {schedules.count()} schedules, executed {executed_count}")
    return f"Executed {executed_count} schedules"


@shared_task
def check_and_execute_rules():
    """
    Check and execute sensor-based automation rules.
    Runs every 30 seconds via Celery Beat.
    """
    from .models import AutomationRule, SensorReading, ActuatorState, ActuationLog, Device
    from django.core.cache import cache
    
    # Check if automation is enabled
    if not cache.get('automation_enabled', True):
        return "Automation disabled"
    
    executed_count = 0
    
    # Sensor readings can come from separate controllers (for example, the LDR
    # is attached to the door/light ESP32 while temperature is attached to the
    # environment ESP32). Resolve each criterion from the newest reading that
    # actually contains that measurement instead of hard-coding one device.
    sensor_fields = {
        'temperature': 'temperature',
        'humidity': 'humidity',
        'distance': 'feeder_level',
        'rain': 'rain_detected',
        'light_level_percentage': 'light_level_percentage',
        'light_raw': 'light_raw',
    }
    action_actuator_types = {
        'open_door': 'door',
        'close_door': 'door',
        'turn_on_light': 'light',
        'turn_off_light': 'light',
    }

    # Get all active sensor-based rules
    rules = AutomationRule.objects.filter(
        is_active=True,
        rule_type__in=['sensor_based', 'detection_based']
    )
    
    for rule in rules:
        try:
            # Check if rule conditions are met
            criteria = rule.criteria
            conditions_met = True
            sensor_values = {}
            
            for key, value in criteria.items():
                # Parse operator and threshold (e.g., '>30' -> operator='>', threshold='30')
                operator = '=='
                threshold_str = str(value).strip()
                
                for op in ['>=', '<=', '==', '>', '<']:
                    if threshold_str.startswith(op):
                        operator = op
                        threshold_str = threshold_str[len(op):].strip()
                        break
                
                try:
                    threshold = float(threshold_str)
                except ValueError:
                    conditions_met = False
                    break
                
                field_name = sensor_fields.get(key)
                if not field_name:
                    conditions_met = False
                    logger.warning("Rule %s uses unsupported sensor %s", rule.name, key)
                    break

                reading_filter = {f'{field_name}__isnull': False}
                # Prefer a measurement reported by the controlled device. This
                # is important for the LDR on the dedicated door/light board.
                latest_reading = SensorReading.objects.filter(
                    device=rule.actuator,
                    **reading_filter,
                ).order_by('-timestamp').first()
                if latest_reading is None:
                    latest_reading = SensorReading.objects.filter(
                        **reading_filter,
                    ).order_by('-timestamp').first()

                actual_value = (
                    getattr(latest_reading, field_name)
                    if latest_reading is not None else None
                )
                if key == 'rain' and actual_value is not None:
                    actual_value = 1 if actual_value else 0
                
                if actual_value is None:
                    conditions_met = False
                    break

                sensor_values[key] = actual_value
                
                # Evaluate condition
                if operator == '>':
                    if not (actual_value > threshold):
                        conditions_met = False
                elif operator == '<':
                    if not (actual_value < threshold):
                        conditions_met = False
                elif operator == '>=':
                    if not (actual_value >= threshold):
                        conditions_met = False
                elif operator == '<=':
                    if not (actual_value <= threshold):
                        conditions_met = False
                elif operator == '==':
                    if not (actual_value == threshold):
                        conditions_met = False
                
                if not conditions_met:
                    break
            
            # Execute action if all conditions are met
            if conditions_met:
                action = rule.action
                device = rule.actuator
                
                # Map action to state
                state_map = {
                    'open_door': 'open',
                    'close_door': 'closed',
                    'turn_on_light': 'on',
                    'turn_off_light': 'off'
                }
                
                new_state = state_map.get(action, 'off')
                actuator_type = action_actuator_types.get(action)
                if actuator_type is None:
                    logger.warning("Rule %s uses unsupported action %s", rule.name, action)
                    continue
                
                # Check if already in this state (avoid repeated executions)
                current_state = ActuatorState.objects.filter(
                    device=device,
                    actuator_type=actuator_type,
                ).first()
                if current_state and current_state.current_state == new_state:
                    continue  # Already in desired state
                
                # Update actuator state
                actuator_state, created = ActuatorState.objects.get_or_create(
                    device=device,
                    actuator_type=actuator_type,
                    defaults={
                        'current_state': new_state,
                        'mode': 'auto',
                        'last_triggered_by': rule.name,
                    }
                )
                
                if not created:
                    actuator_state.current_state = new_state
                    actuator_state.mode = 'auto'
                    actuator_state.last_triggered_by = rule.name
                    actuator_state.save()
                
                # Log the actuation
                ActuationLog.objects.create(
                    device=device,
                    action=STATE_TO_ACTION.get(new_state, 'turn_on'),
                    source='rule',
                    triggered_by=rule.name,
                    rule=rule,
                    metadata={
                        'actuator_type': actuator_type,
                        'new_state': new_state,
                        'sensor_values': sensor_values,
                    },
                )
                
                executed_count += 1
                logger.info(f"Executed rule: {rule.name} - {action}")
                
        except Exception as e:
            logger.error(f"Error executing rule {rule.name}: {str(e)}")
    
    if executed_count > 0:
        logger.info(f"Executed {executed_count} automation rules")
    return f"Executed {executed_count} rules"


@shared_task  
def execute_scheduled_feeding():
    """
    Execute scheduled feeding tasks.
    Runs every minute via Celery Beat.
    """
    from feeding.models import FeedSchedule, FeedLog
    from django.core.cache import cache
    
    # Check if automation is enabled
    if not cache.get('automation_enabled', True):
        return "Automation disabled"
    
    # Use local time instead of UTC for schedule matching
    now = timezone.localtime(timezone.now())
    current_time = now.time().replace(second=0, microsecond=0)
    current_day = (now.weekday() + 1) % 7  # Convert to 0=Sunday format
    
    logger.info(f"Checking feeding schedules at {current_time} (day {current_day})")
    
    executed_count = 0
    
    # Get all active schedules for current time
    schedules = FeedSchedule.objects.filter(
        is_active=True,
        schedule_time=current_time
    )
    
    logger.info(f"Found {schedules.count()} feeding schedules matching time {current_time}")
    
    for schedule in schedules:
        # Check if today is in the schedule
        days_of_week = schedule.days_of_week
        logger.info(f"Schedule {schedule.id}: {schedule.schedule_time}, days={days_of_week}, current_day={current_day}")
        
        if days_of_week and current_day not in days_of_week:
            logger.info(f"  Skipping - day {current_day} not in {days_of_week}")
            continue
        
        logger.info(f"  Executing feeding schedule for {schedule.feeder.name}")
        
        try:
            # Update feeder actuator state to trigger feeding on ESP32
            feeder = schedule.feeder
            from .models import ActuatorState, ActuationLog, Device
            
            # Get the ESP32 device that controls the physical servo
            try:
                esp32_device = Device.objects.get(device_id='kamotech_esp32_001')
            except Device.DoesNotExist:
                logger.error("ESP32 device not found! Cannot trigger feeder.")
                continue
            
            # Update the ESP32's feeder actuator state
            actuator_state, created = ActuatorState.objects.get_or_create(
                device=esp32_device,
                actuator_type='feeder',
                defaults={'current_state': 'on', 'mode': 'auto'}
            )
            
            if not created:
                actuator_state.current_state = 'on'
                actuator_state.mode = 'auto'
                actuator_state.last_triggered_by = f'Schedule: {schedule.schedule_time}'
                actuator_state.save()
            
            logger.info("Updated ESP32 feeder actuator to ON (auto mode)")
            
            # Schedule auto-off after 10 seconds (ESP32 polls every 5s, feeding takes 3s)
            reset_feeder_state.apply_async(
                args=[esp32_device.id],
                countdown=10
            )
            
            # Log the feeding (keep logging to feeder device for record keeping)
            ActuationLog.objects.create(
                device=feeder,
                action='turn_on',
                source='rule',
                triggered_by=f"Schedule: {schedule.schedule_time}"
            )
            
            # Create feed log
            FeedLog.objects.create(
                feeder=feeder,
                amount_grams=schedule.amount_grams,
                schedule=schedule,
                fed_at=now
            )
            
            executed_count += 1
            logger.info(f"Executed feeding schedule: {schedule}")
            
        except Exception as e:
            logger.error(f"Error executing feeding schedule {schedule}: {str(e)}")
    
    if executed_count > 0:
        logger.info(f"Executed {executed_count} feeding schedules")
    return f"Executed {executed_count} feeding schedules"


@shared_task
def reset_feeder_state(device_id):
    """
    Reset feeder actuator state back to OFF after feeding completes.
    Called 10 seconds after feeding is triggered.
    
    Args:
        device_id: ID of the Device (ESP32) to reset
    """
    from .models import ActuatorState, Device
    
    try:
        device = Device.objects.get(id=device_id)
        
        actuator_state = ActuatorState.objects.get(
            device=device,
            actuator_type='feeder'
        )
        
        # Only reset if still in auto mode (don't interfere with manual control)
        if actuator_state.mode == 'auto':
            actuator_state.current_state = 'off'
            actuator_state.mode = 'manual'
            actuator_state.last_triggered_by = 'Auto-reset after feeding'
            actuator_state.save()
            logger.info(f"Reset feeder actuator to OFF for device {device.device_id}")
        else:
            logger.info(f"Skipped reset - feeder in manual mode for device {device.device_id}")
            
    except (Device.DoesNotExist, ActuatorState.DoesNotExist) as e:
        logger.error(f"Failed to reset feeder state: {str(e)}")
    except Exception as e:
        logger.error(f"Error resetting feeder state: {str(e)}")
    
    return f"Reset feeder for device {device_id}"
