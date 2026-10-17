"""One local inference loop shared by scheduled, manual and live viewers."""

import logging
import json
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from redis import Redis

logger = logging.getLogger(__name__)
PREFIX = "gohmotech:live-detection:v1"
VIEWER_TTL = 40
IDLE_GRACE = 30


def redis_client():
    return Redis.from_url(settings.CACHES["default"]["LOCATION"], decode_responses=True)


def key(camera_id, suffix):
    return f"{PREFIX}:{camera_id}:{suffix}"


def schedule_window(now=None):
    """Run during the first two minutes of each Manila clock hour."""
    now = timezone.localtime(now or timezone.now())
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=2)
    return start <= now < end, end, start + timedelta(hours=1)


def demand(camera_id, now=None, client=None):
    client = client or redis_client()
    now = now or timezone.now()
    viewers = key(camera_id, "viewers")
    client.zremrangebyscore(viewers, "-inf", time.time())
    viewer_count = client.zcard(viewers)
    manual_key = key(camera_id, "manual")
    manual_token = client.get(manual_key)
    manual = bool(manual_token and client.zscore(viewers, manual_token) is not None)
    if manual_token and not manual:
        # Older manual sessions and sessions whose initiating page went idle
        # must not keep inference running indefinitely.
        client.delete(manual_key)
    scheduled, _, next_start = schedule_window(now)
    mode = "Manual" if manual else "Live Viewing" if viewer_count else "Scheduled" if scheduled else "Inactive"
    return mode, viewer_count, next_start


def status(camera_id, client=None):
    client = client or redis_client()
    mode, viewers, next_start = demand(camera_id, client=client)
    raw = client.hgetall(key(camera_id, "latest"))
    running = bool(client.exists(key(camera_id, "loop")))
    return {
        "mode": mode, "running": running, "viewers": viewers,
        "manual_enabled": bool(client.exists(key(camera_id, "manual"))),
        "next_scheduled_at": next_start.isoformat(),
        "latest": {
            "id": int(raw["id"]), "detection_count": int(raw["count"]),
            "confidence": float(raw["confidence"]),
            "detections": json.loads(raw["detections"]),
            "persons": json.loads(raw.get("persons", "{}")),
            "frame_width": int(raw.get("frame_width", 0)),
            "frame_height": int(raw.get("frame_height", 0)),
            "timestamp": raw["timestamp"],
        } if raw.get("id") else None,
    }


def viewer_heartbeat(camera_id, token, client=None):
    client = client or redis_client()
    # Tokens are unguessable, bounded client identifiers; never accept Redis syntax.
    uuid.UUID(token)
    client.zadd(key(camera_id, "viewers"), {token: time.time() + VIEWER_TTL})
    client.expire(key(camera_id, "viewers"), VIEWER_TTL + 60)


def viewer_leave(camera_id, token, client=None):
    uuid.UUID(token)
    (client or redis_client()).zrem(key(camera_id, "viewers"), token)


def run_inference(frame, camera, detector):
    """Use the existing goat, re-identification and person pipelines locally."""
    import cv2
    from .ml_utils import detect_and_identify_goats
    from .models import Detection, MLModel
    from .views import get_active_detector, _extract_persons
    from iot.models import Device

    result = detect_and_identify_goats(frame, detector, camera, enable_reid=True)
    model = MLModel.objects.filter(category="goat", is_active=True).first()
    device = Device.objects.filter(device_id=camera.camera_id, device_type="camera").first()
    row = Detection.objects.create(
        model=model, camera=device, goat_count=result["detection_count"],
        confidence=result["confidence"], bounding_boxes=result["detections"], processed=True,
    )
    persons = {}
    person_detector = get_active_detector("person")
    if person_detector is not None:
        try:
            found = _extract_persons(person_detector, person_detector.detect(frame))
            found = [p for p in found if p.get("confidence", 0) >= getattr(settings, "PERSON_CONFIDENCE_THRESHOLD", 0.5)]
            persons = {"count": len(found), "detections": found}
            if found:
                from security.services import record_person_detection
                ok, jpg = cv2.imencode(".jpg", frame)
                record_person_detection(
                    camera=camera, confidence=max(p["confidence"] for p in found),
                    bounding_boxes=found, snapshot_bytes=jpg.tobytes() if ok else None,
                    detection_type="person",
                )
        except Exception:
            logger.exception("Person detection path failed")
    redis_client().hset(key(camera.id, "latest"), mapping={
        "id": row.id, "count": row.goat_count, "confidence": row.confidence,
        "detections": json.dumps(result["detections"]), "persons": json.dumps(persons),
        "timestamp": row.timestamp.isoformat(),
        "frame_width": frame.shape[1], "frame_height": frame.shape[0],
    })
    return row
