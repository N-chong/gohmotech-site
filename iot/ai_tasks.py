"""
Celery tasks for AI-powered Smart Door Automation

This module handles:
- Scheduled goat count checks
- Missing goat detection
- Automated door control based on AI detection
- Alert creation and notifications
"""

from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging
import cv2
import numpy as np
import time

logger = logging.getLogger(__name__)


@shared_task(name='iot.tasks.scheduled_door_check')
def scheduled_door_check(camera_id=None):
    """
    Scheduled task to check goat count and control door.
    
    This task runs at configured times (e.g., 7:30 PM) to:
    1. Capture frame from camera
    2. Run AI detection + identification
    3. Count detected goats
    4. Compare with expected count (active goats in DB)
    5. Close door if all present, else send alert
    
    Args:
        camera_id: Optional camera ID (uses first active camera if None)
        
    Returns:
        Dict with check results
    """
    from iot.goat_models import IPCamera
    from iot.models import Goat
    from ml_models.ml_utils import detect_and_identify_goats
    
    logger.info("🔍 Starting scheduled door check...")
    
    try:
        # Step 1: Get camera
        if camera_id:
            camera = IPCamera.objects.get(device_id=camera_id)
        else:
            camera = IPCamera.objects.filter(is_active=True).first()
        
        if not camera:
            logger.error("No active camera found")
            return {'status': 'error', 'message': 'No active camera'}
        
        # Step 2: Capture frame from camera
        frame = capture_frame_from_camera(camera)
        if frame is None:
            logger.error(f"Failed to capture frame from {camera.name}")
            return {'status': 'error', 'message': 'Frame capture failed'}
        
        # Step 3: Run AI detection + identification
        from ml_models.views import get_active_detector
        detector = get_active_detector()
        
        if not detector:
            logger.error("No active ML model found")
            return {'status': 'error', 'message': 'No active detector'}
        
        results = detect_and_identify_goats(
            image=frame,
            detector=detector,
            camera=camera,
            enable_reid=True
        )
        
        detected_count = len(results['identified_goats']) + len(results['new_goats'])
        identified_goat_ids = [g['goat_id'] for g in results['identified_goats']]
        new_goat_ids = [g['goat_id'] for g in results['new_goats']]
        
        logger.info(f"Detected {detected_count} goats: {identified_goat_ids + new_goat_ids}")
        
        # Step 4: Get expected count (active goats)
        active_goats = Goat.objects.filter(status='active')
        expected_count = active_goats.count()
        expected_goat_ids = list(active_goats.values_list('goat_id', flat=True))
        
        logger.info(f"Expected {expected_count} active goats: {expected_goat_ids}")
        
        # Step 5: Compare and make decision
        if detected_count >= expected_count:
            # All goats present - close door
            logger.info("✅ All goats present. Closing door...")
            
            door_result = close_door_safely(
                source='ai_scheduled_check',
                metadata={
                    'detected_count': detected_count,
                    'expected_count': expected_count,
                    'detected_goats': identified_goat_ids + new_goat_ids,
                    'check_time': timezone.now().isoformat()
                }
            )
            
            # Resolve any existing alerts
            resolve_missing_goat_alerts()
            
            # Send positive notification
            try:
                from iot.notification_service import get_notification_service
                service = get_notification_service()
                service.send_all_goats_present_notification(detected_count)
                service.send_door_status_notification('closed', {
                    'detected_count': detected_count,
                    'expected_count': expected_count
                })
            except Exception as e:
                logger.error(f"Failed to send success notification: {e}")
            
            return {
                'status': 'success',
                'action': 'door_closed',
                'detected_count': detected_count,
                'expected_count': expected_count,
                'all_present': True,
                'door_state': door_result
            }
        
        else:
            # Some goats missing - hold door and alert
            missing_count = expected_count - detected_count
            logger.warning(f"⚠️ {missing_count} goat(s) missing! Holding door open...")
            
            # Find which specific goats are missing
            all_detected_ids = set(identified_goat_ids + new_goat_ids)
            missing_goat_ids = [gid for gid in expected_goat_ids if gid not in all_detected_ids]
            
            logger.warning(f"Missing goats: {missing_goat_ids}")
            
            # Create or update missing goat alert
            alert = create_missing_goat_alert(
                camera=camera,
                detected_count=detected_count,
                expected_count=expected_count,
                missing_goat_ids=missing_goat_ids,
                frame_snapshot=frame
            )
            
            # Hold door open
            hold_door_open(
                source='ai_missing_goats',
                metadata={
                    'detected_count': detected_count,
                    'expected_count': expected_count,
                    'missing_count': missing_count,
                    'missing_goats': missing_goat_ids,
                    'alert_id': alert.id if alert else None
                }
            )
            
            # Send door status notification
            try:
                from iot.notification_service import get_notification_service
                service = get_notification_service()
                service.send_door_status_notification('held_open', {
                    'missing_count': missing_count,
                    'missing_goats': missing_goat_ids
                })
            except Exception as e:
                logger.error(f"Failed to send door status notification: {e}")
            
            return {
                'status': 'warning',
                'action': 'door_held_open',
                'detected_count': detected_count,
                'expected_count': expected_count,
                'missing_count': missing_count,
                'missing_goats': missing_goat_ids,
                'all_present': False,
                'alert_created': alert.id if alert else None
            }
    
    except Exception as e:
        logger.error(f"Scheduled door check failed: {e}", exc_info=True)
        return {
            'status': 'error',
            'message': str(e)
        }


def capture_frame_from_camera(camera):
    """
    Capture a single frame from camera RTSP stream.
    
    Args:
        camera: IPCamera instance
        
    Returns:
        numpy.ndarray (BGR image) or None if failed
    """
    try:
        # Try RTSP stream first
        if camera.rtsp_url:
            cap = cv2.VideoCapture(camera.rtsp_url)
            
            if not cap.isOpened():
                logger.error("Failed to open RTSP stream for camera %s", camera.name)
                return None
            
            # Read frame
            ret, frame = cap.read()
            cap.release()
            
            if ret and frame is not None:
                logger.info(f"✅ Frame captured from RTSP: {frame.shape}")
                return frame
        
        # Fallback: Try HTTP snapshot URL
        if camera.snapshot_url:
            import requests
            response = requests.get(camera.snapshot_url, timeout=10)
            
            if response.status_code == 200:
                # Decode image
                img_array = np.frombuffer(response.content, np.uint8)
                frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                
                if frame is not None:
                    logger.info(f"✅ Frame captured from HTTP: {frame.shape}")
                    return frame
        
        logger.error("No valid camera URL available")
        return None
        
    except Exception as e:
        logger.error(f"Frame capture error: {e}")
        return None


def close_door_safely(source='system', metadata=None):
    """
    Safely close the automated door.
    
    Args:
        source: Who/what triggered the close (e.g., 'ai_scheduled_check', 'manual', 'rule')
        metadata: Optional dict with additional context
        
    Returns:
        Dict with door state info
    """
    from iot.models import Device, ActuatorState, ActuationLog
    
    try:
        # Find door actuator
        door_device = Device.objects.filter(
            device_type='actuator',
            name__icontains='door'
        ).first()
        
        if not door_device:
            logger.error("Door actuator device not found")
            return {'status': 'error', 'message': 'Door device not found'}
        
        # Get or create actuator state
        actuator_state, created = ActuatorState.objects.get_or_create(
            device=door_device,
            actuator_type='door',
            defaults={
                'current_state': 'open',
                'mode': 'auto'
            }
        )
        
        # Update state to closed
        actuator_state.current_state = 'closed'
        actuator_state.last_triggered_by = source
        actuator_state.save()
        
        # Log the actuation
        ActuationLog.objects.create(
            device=door_device,          # FK is 'device' (there is no 'actuator' field)
            action='close',              # valid ACTION_TYPES value (was 'close_door')
            source='system',             # AI-driven automated decision
            triggered_by=source,         # descriptive origin, e.g. 'ai_scheduled_check'
            result='success',
            metadata=metadata or {}
        )
        
        logger.info(f"✅ Door closed by {source}")
        
        return {
            'status': 'success',
            'state': 'closed',
            'triggered_by': source
        }
        
    except Exception as e:
        logger.error(f"Failed to close door: {e}")
        return {'status': 'error', 'message': str(e)}


def hold_door_open(source='system', metadata=None):
    """
    Hold the door open (prevent auto-close).
    
    Args:
        source: Reason for holding door open
        metadata: Additional context
        
    Returns:
        Dict with result
    """
    from iot.models import Device, ActuatorState, ActuationLog
    
    try:
        door_device = Device.objects.filter(
            device_type='actuator',
            name__icontains='door'
        ).first()
        
        if not door_device:
            return {'status': 'error', 'message': 'Door device not found'}
        
        actuator_state, _ = ActuatorState.objects.get_or_create(
            device=door_device,
            actuator_type='door',
            defaults={'current_state': 'open', 'mode': 'auto'}
        )
        
        # Keep door open
        actuator_state.current_state = 'open'
        actuator_state.last_triggered_by = source
        actuator_state.save()
        
        # Log
        ActuationLog.objects.create(
            device=door_device,          # FK is 'device' (there is no 'actuator' field)
            action='open',               # holding open == desired state 'open'
            source='system',             # AI-driven automated decision
            triggered_by=source,         # descriptive origin, e.g. 'ai_missing_goats'
            result='success',
            metadata={**(metadata or {}), 'operation': 'hold_open'},
        )
        
        logger.info(f"⚠️ Door held open by {source}")
        
        return {'status': 'success', 'state': 'held_open'}
        
    except Exception as e:
        logger.error(f"Failed to hold door: {e}")
        return {'status': 'error', 'message': str(e)}


def create_missing_goat_alert(camera, detected_count, expected_count, missing_goat_ids, frame_snapshot=None):
    """
    Create or update a missing goat alert.
    
    Args:
        camera: IPCamera instance
        detected_count: Number of goats detected
        expected_count: Number of goats expected
        missing_goat_ids: List of missing goat IDs
        frame_snapshot: Optional frame image to save
        
    Returns:
        MissingGoatAlert instance or None
    """
    from iot.goat_models import MissingGoatAlert
    from iot.models import Goat
    from django.core.files.base import ContentFile
    
    try:
        missing_count = expected_count - detected_count
        
        # Check if there's already an active alert
        existing_alert = MissingGoatAlert.objects.filter(
            is_resolved=False,
            camera=camera
        ).first()
        
        if existing_alert:
            # Update existing alert
            existing_alert.missing_count = missing_count
            existing_alert.detected_count = detected_count
            existing_alert.expected_count = expected_count
            existing_alert.last_checked = timezone.now()
            existing_alert.save()
            
            # Update missing goats
            missing_goats = Goat.objects.filter(goat_id__in=missing_goat_ids)
            existing_alert.missing_goats.set(missing_goats)
            
            logger.info(f"Updated existing alert #{existing_alert.id}")
            
            # Send notification
            send_missing_goat_notification(existing_alert, is_update=True)
            
            return existing_alert
        
        else:
            # Create new alert
            severity = calculate_alert_severity(missing_count, expected_count)
            
            alert = MissingGoatAlert.objects.create(
                camera=camera,
                missing_count=missing_count,
                detected_count=detected_count,
                expected_count=expected_count,
                severity=severity,
                description=f"{missing_count} goat(s) missing from goat house"
            )
            
            # Add missing goats
            missing_goats = Goat.objects.filter(goat_id__in=missing_goat_ids)
            alert.missing_goats.set(missing_goats)
            
            # Save snapshot if provided
            if frame_snapshot is not None:
                try:
                    _, img_encoded = cv2.imencode('.jpg', frame_snapshot)
                    img_bytes = img_encoded.tobytes()
                    alert.snapshot_image.save(
                        f'alert_{alert.id}_snapshot.jpg',
                        ContentFile(img_bytes),
                        save=True
                    )
                except Exception as e:
                    logger.error(f"Failed to save alert snapshot: {e}")
            
            logger.warning(f"🚨 Created missing goat alert #{alert.id}")
            
            # Send notification
            send_missing_goat_notification(alert, is_update=False)
            
            return alert
            
    except Exception as e:
        logger.error(f"Failed to create missing goat alert: {e}", exc_info=True)
        return None


def calculate_alert_severity(missing_count, expected_count):
    """
    Calculate alert severity based on missing goat count.
    
    Args:
        missing_count: Number of missing goats
        expected_count: Total expected goats
        
    Returns:
        'low', 'medium', or 'high'
    """
    if expected_count == 0:
        return 'low'
    
    missing_percentage = (missing_count / expected_count) * 100
    
    if missing_percentage >= 50:
        return 'high'  # 50%+ missing
    elif missing_percentage >= 25:
        return 'medium'  # 25-49% missing
    else:
        return 'low'  # <25% missing


def resolve_missing_goat_alerts():
    """
    Resolve all active missing goat alerts.
    Called when all goats are detected.
    """
    from iot.goat_models import MissingGoatAlert
    
    try:
        active_alerts = MissingGoatAlert.objects.filter(is_resolved=False)
        count = active_alerts.count()
        
        for alert in active_alerts:
            alert.resolve()  # Uses the model's resolve() method
            logger.info(f"✅ Resolved alert #{alert.id}")
        
        if count > 0:
            logger.info(f"Resolved {count} missing goat alert(s)")
        
        return count
        
    except Exception as e:
        logger.error(f"Failed to resolve alerts: {e}")
        return 0


def send_missing_goat_notification(alert, is_update=False):
    """
    Send notification about missing goats through all configured channels.
    
    Args:
        alert: MissingGoatAlert instance
        is_update: Whether this is an update to existing alert
    """
    try:
        from iot.notification_service import get_notification_service
        
        # Get notification service
        service = get_notification_service()
        
        # Send through all enabled channels
        results = service.send_missing_goat_notification(alert)
        
        logger.info(f"📧 Notification sent for alert #{alert.id}: {results}")
        
        return results
        
    except Exception as e:
        logger.error(f"Failed to send notification: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}


@shared_task(name='iot.tasks.start_realtime_detection')
def start_realtime_detection(camera_id=None, stream_url=None, fps=4, enable_reid=False, max_frames=None):
    """
    Run real-time detection loop and push updates via WebSocket.

    Args:
        camera_id: IPCamera.camera_id or numeric ID
        stream_url: RTSP/HTTP stream URL if not using IPCamera
        fps: Target processing rate
        enable_reid: Enable re-identification
        max_frames: Optional cap for frames processed
    """
    from django.core.cache import cache
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    from ml_models.views import get_active_detector
    from ml_models.ml_utils import detect_and_identify_goats
    from ml_models.models import MLModel, Detection
    from iot.models import Device
    from iot.goat_models import IPCamera
    from iot.camera_utils import CameraStreamManager

    detector = get_active_detector()
    if not detector:
        logger.error("No active detector available for real-time detection")
        return {'status': 'error', 'message': 'No active detector'}

    fps = max(1, int(fps or 1))
    interval = 1.0 / fps
    cache_key = f"realtime_detection_active_{camera_id or 'stream'}"
    cache.set(cache_key, True, None)

    camera = None
    device = None
    stream = None
    cap = None

    if camera_id:
        try:
            camera = IPCamera.objects.get(camera_id=camera_id)
        except IPCamera.DoesNotExist:
            try:
                camera = IPCamera.objects.get(id=camera_id)
            except IPCamera.DoesNotExist:
                camera = None

    if camera:
        device = Device.objects.filter(device_id=camera.camera_id).first()
        stream = CameraStreamManager().get_stream(camera.id)
        if not stream:
            return {'status': 'error', 'message': 'Camera stream unavailable'}
    elif stream_url:
        cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return {'status': 'error', 'message': 'Failed to open stream URL'}
    else:
        return {'status': 'error', 'message': 'No camera_id or stream_url provided'}

    channel_layer = get_channel_layer()
    frames_processed = 0

    try:
        while cache.get(cache_key, True):
            start_time = time.perf_counter()

            frame = None
            if stream:
                frame = stream.get_frame()
            elif cap:
                ok, frame = cap.read()
                if not ok:
                    frame = None

            if frame is None:
                time.sleep(0.2)
                continue

            result = detect_and_identify_goats(
                image=frame,
                detector=detector,
                camera=camera,
                enable_reid=enable_reid
            )

            active_model = MLModel.objects.filter(category='goat', is_active=True).first()
            detection = Detection.objects.create(
                model=active_model,
                camera=device,
                goat_count=result['detection_count'],
                confidence=result['confidence'],
                bounding_boxes=result['detections'],
                processed=True
            )

            payload = {
                'detection_id': detection.id,
                'camera_id': camera.camera_id if camera else None,
                'goat_count': result['detection_count'],
                'confidence': result['confidence'],
                'detections': result['detections'],
                'reid_enabled': result['reid_enabled'],
                'timestamp': detection.timestamp.isoformat()
            }

            async_to_sync(channel_layer.group_send)(
                'detections',
                {'type': 'detection_update', 'data': payload}
            )

            frames_processed += 1
            if max_frames and frames_processed >= max_frames:
                break

            elapsed = time.perf_counter() - start_time
            if elapsed < interval:
                time.sleep(interval - elapsed)

        return {'status': 'stopped', 'frames_processed': frames_processed}

    except Exception as e:
        logger.error(f"Real-time detection failed: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}

    finally:
        if cap:
            cap.release()
        if stream:
            stream.stop()


@shared_task(name='iot.tasks.stop_realtime_detection')
def stop_realtime_detection(camera_id=None):
    """Stop the real-time detection loop for a camera or stream."""
    from django.core.cache import cache

    cache_key = f"realtime_detection_active_{camera_id or 'stream'}"
    cache.set(cache_key, False, None)
    return {'status': 'stopping', 'camera_id': camera_id}


@shared_task(name='iot.tasks.check_missing_goats_periodic')
def check_missing_goats_periodic():
    """
    Periodic task to check for goats that haven't been seen recently.
    
    Runs independently of door automation to catch goats that might have
    gone missing during the day.
    """
    from iot.models import Goat
    
    logger.info("🔍 Checking for recently missing goats...")
    
    try:
        # Find goats that haven't been seen in last 2 hours
        threshold = timezone.now() - timedelta(hours=2)
        
        potentially_missing = Goat.objects.filter(
            status='active',
            last_seen__lt=threshold
        )
        
        count = potentially_missing.count()
        
        if count > 0:
            missing_ids = list(potentially_missing.values_list('goat_id', flat=True))
            logger.warning(f"⚠️ {count} goat(s) not seen recently: {missing_ids}")
            
            # Update status to 'missing' (admin can manually revert if false positive)
            potentially_missing.update(status='missing')
            
            return {
                'status': 'warning',
                'potentially_missing_count': count,
                'goat_ids': missing_ids
            }
        else:
            logger.info("✅ All active goats seen recently")
            return {
                'status': 'ok',
                'potentially_missing_count': 0
            }
            
    except Exception as e:
        logger.error(f"Periodic missing goat check failed: {e}")
        return {'status': 'error', 'message': str(e)}
