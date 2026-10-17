"""
Celery tasks for ML Models

Background tasks for:
- Batch ML inference processing
- Model training/fine-tuning (future)
- Detection data cleanup
"""

from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


@shared_task(name='ml_models.tasks.ensure_live_detection')
def ensure_live_detection():
    """Beat watchdog: start at most one Pi-local inference loop per camera."""
    import uuid
    from iot.goat_models import IPCamera
    from .live_detection import demand, key, redis_client

    client = redis_client()
    for camera_id in IPCamera.objects.filter(is_active=True, enable_goat_detection=True).values_list('id', flat=True):
        mode, _, _ = demand(camera_id, client=client)
        if mode == 'Inactive':
            continue
        token = str(uuid.uuid4())
        if client.set(key(camera_id, 'loop'), token, nx=True, ex=90):
            try:
                run_live_detection.delay(camera_id, token)
            except Exception:
                client.delete(key(camera_id, 'loop'))
                raise


@shared_task(name='ml_models.tasks.run_live_detection', time_limit=7 * 24 * 3600,
             soft_time_limit=7 * 24 * 3600 - 60)
def run_live_detection(camera_id, token):
    """Process full-resolution camera frames on the Pi; publish only small results."""
    import time
    from django.db import close_old_connections
    from iot.goat_models import IPCamera
    from iot.camera_utils import CameraStream
    from .live_detection import IDLE_GRACE, demand, key, redis_client, run_inference
    from .views import get_active_detector, _detectors

    client = redis_client()
    lock = key(camera_id, 'loop')
    stream = None
    processed = 0
    idle_since = None
    try:
        if client.get(lock) != token or demand(camera_id, client=client)[0] == 'Inactive':
            return {'status': 'no_demand'}
        camera = IPCamera.objects.get(id=camera_id, is_active=True, enable_goat_detection=True)
        detector = get_active_detector('goat')
        if detector is None:
            logger.error('Live detection has no active goat model')
            return {'status': 'no_model'}
        stream = CameraStream(camera)
        stream.start()
        while True:
            if client.get(lock) != token:
                break
            client.expire(lock, 90)
            mode, _, _ = demand(camera_id, client=client)
            if mode == 'Inactive':
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since >= IDLE_GRACE:
                    break
                time.sleep(1)
                continue
            idle_since = None
            frame = stream.get_frame()
            if frame is None:
                time.sleep(1)
                continue
            tick = time.monotonic()
            interval = max(2, min(60, camera.detection_interval_seconds or 2))
            try:
                close_old_connections()
                camera.refresh_from_db(fields=['detection_interval_seconds'])
                interval = max(2, min(60, camera.detection_interval_seconds or 2))
                run_inference(frame, camera, detector)
                processed += 1
            except Exception:
                logger.exception('Pi-local live inference failed for camera %s', camera_id)
                time.sleep(3)
            time.sleep(max(0, interval - (time.monotonic() - tick)))
        return {'status': 'stopped', 'frames_processed': processed}
    finally:
        if stream:
            stream.stop()
        if client.get(lock) == token:
            client.delete(lock)
        _detectors.clear()
        close_old_connections()


@shared_task
def process_pending_detections():
    """
    Process any pending detection images.
    Useful for batch processing or retry logic.
    """
    from .models import Detection
    from .ml_utils import get_detector
    
    pending = Detection.objects.filter(processed=False)
    
    if not pending.exists():
        return "No pending detections"
    
    detector = get_detector()
    if not detector:
        logger.error("No active ML model found")
        return "No active model"
    
    processed_count = 0
    for detection in pending:
        try:
            # Mark as processed
            detection.processed = True
            detection.save()
            processed_count += 1
        except Exception as e:
            logger.error(f"Error processing detection {detection.id}: {e}")
    
    return f"Processed {processed_count} detections"


@shared_task
def cleanup_old_detections(days=30):
    """
    Clean up old detection records to save database space.
    
    Args:
        days: Number of days to keep (default: 30)
    """
    from .models import Detection
    
    cutoff_date = timezone.now() - timedelta(days=days)
    old_detections = Detection.objects.filter(timestamp__lt=cutoff_date)
    
    count = old_detections.count()
    old_detections.delete()
    
    logger.info(f"Cleaned up {count} old detections")
    return f"Deleted {count} detections older than {days} days"


@shared_task
def generate_detection_report(start_date, end_date):
    """
    Generate a detection summary report for a date range.
    
    Args:
        start_date: Start date (ISO format string)
        end_date: End date (ISO format string)
    """
    from .models import Detection
    from django.db.models import Count, Avg, Sum
    from datetime import datetime
    
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    
    detections = Detection.objects.filter(
        timestamp__gte=start,
        timestamp__lte=end
    )
    
    stats = {
        'total_detections': detections.count(),
        'total_goats': detections.aggregate(total=Sum('goat_count'))['total'] or 0,
        'average_confidence': detections.aggregate(avg=Avg('confidence'))['avg'] or 0,
        'cameras': detections.values('camera__name').annotate(count=Count('id')),
    }
    
    logger.info(f"Generated detection report: {stats}")
    return stats
