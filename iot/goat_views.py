"""
Enhanced Goat Management Views - Phase 5
Includes AI detection integration, status management, and detailed analytics
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.cache import cache
from django.db import transaction
from django.db.utils import IntegrityError
from django.db.models import Q, Avg, Prefetch
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import json
import logging
import math
import uuid

from PIL import Image, UnidentifiedImageError
from marketplace.image_utils import optimize_marketplace_image

logger = logging.getLogger(__name__)

from .goat_models import (
    Goat, GoatWeightMeasurement, GoatImage, GoatDetectionHistory, MissingGoatAlert
)
from .forms import BLEBeaconForm, GoatForm
from .device_authentication import device_key_required
from marketplace.decorators import farm_access_required, farm_owner_required
from marketplace.auth import can_manage_farm


SCALE_DEVICE_ID = 'kamotech_scale_esp32_001'
SCALE_CACHE_TTL_SECONDS = 15
SCALE_OFFLINE_AFTER_SECONDS = 5
MIN_GOAT_WEIGHT_KG = Decimal('0.10')
MAX_GOAT_WEIGHT_KG = Decimal('300.00')
MAX_GOAT_IMAGE_BYTES = 5 * 1024 * 1024
MAX_GOAT_IMAGE_PIXELS = 25_000_000


def _validated_goat_image(upload):
    """Verify and normalize a farm image before it reaches public media."""
    if not upload or getattr(upload, 'size', 0) > MAX_GOAT_IMAGE_BYTES:
        raise ValidationError('Goat photos must be 5 MB or smaller.')
    content_type = (getattr(upload, 'content_type', '') or '').lower()
    if content_type not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise ValidationError('Upload a valid JPG, PNG, or WebP image.')
    try:
        upload.seek(0)
        with Image.open(upload) as candidate:
            width, height = candidate.size
            if width * height > MAX_GOAT_IMAGE_PIXELS:
                raise ValidationError('Goat photos must be 25 megapixels or smaller.')
            candidate.verify()
        upload.seek(0)
        return optimize_marketplace_image(upload)
    except ValidationError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise ValidationError('The selected goat photo could not be verified.') from exc
    finally:
        try:
            upload.seek(0)
        except (AttributeError, OSError):
            pass


def _scale_cache_key(device_id=SCALE_DEVICE_ID):
    return f'iot:scale:latest:{device_id}'


def _read_json_request(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _current_scale_state():
    snapshot = cache.get(_scale_cache_key())
    offline = {
        'connected': False,
        'hx711_ready': False,
        'weight_detected': False,
        'stable': False,
        'weight_kg': None,
        'variation_kg': None,
        'status': 'Scale Offline',
        'received_at': None,
    }
    if not snapshot:
        return offline

    received_at = parse_datetime(snapshot.get('received_at', ''))
    if received_at is None:
        return offline
    if timezone.is_naive(received_at):
        received_at = timezone.make_aware(received_at, timezone.get_current_timezone())
    age_seconds = max(0, (timezone.now() - received_at).total_seconds())
    if age_seconds > SCALE_OFFLINE_AFTER_SECONDS:
        return {**offline, 'received_at': snapshot.get('received_at')}

    state = {
        **snapshot,
        'connected': True,
        'age_seconds': round(age_seconds, 2),
    }
    if not state.get('hx711_ready'):
        state['status'] = 'Scale Unavailable'
    elif not state.get('valid'):
        state['status'] = 'Invalid Sensor Reading'
    elif not state.get('weight_detected'):
        state['status'] = 'Waiting for Weight'
    elif state.get('stable'):
        state['status'] = 'Stable Weight'
    else:
        state['status'] = 'Stabilizing'
    return state


def _measurement_payload(measurement, duplicate=False):
    return {
        'ok': True,
        'duplicate': duplicate,
        'measurement': {
            'id': measurement.pk,
            'goat_id': measurement.goat.goat_id,
            'goat_name': measurement.goat.name,
            'weight_kg': f'{measurement.weight_kg:.2f}',
            'unit': 'kg',
            'source': measurement.source,
            'source_display': measurement.get_source_display(),
            'measured_at': timezone.localtime(measurement.measured_at).isoformat(),
        },
    }


@csrf_exempt
@device_key_required
@require_POST
def scale_reading_ingest(request):
    """Receive one transient HX711 snapshot without creating history records."""
    payload = _read_json_request(request)
    if payload is None:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON payload.'}, status=400)

    device_id = str(payload.get('device_id', '')).strip()
    if device_id != SCALE_DEVICE_ID:
        return JsonResponse({'ok': False, 'error': 'Unknown scale device.'}, status=400)

    hx711_ready = payload.get('hx711_ready') is True
    raw_weight = payload.get('weight_kg')
    weight_kg = None
    valid = False
    try:
        candidate = float(raw_weight)
        if math.isfinite(candidate) and 0 <= candidate <= float(MAX_GOAT_WEIGHT_KG):
            weight_kg = round(candidate, 2)
            valid = hx711_ready
    except (TypeError, ValueError):
        pass

    variation_kg = None
    try:
        candidate_variation = float(payload.get('variation_kg'))
        if math.isfinite(candidate_variation) and candidate_variation >= 0:
            variation_kg = round(candidate_variation, 3)
    except (TypeError, ValueError):
        pass

    weight_detected = bool(payload.get('weight_detected')) and valid
    stable = bool(payload.get('stable')) and weight_detected
    received_at = timezone.now()
    snapshot = {
        'device_id': device_id,
        'hx711_ready': hx711_ready,
        'valid': valid,
        'weight_detected': weight_detected,
        'stable': stable,
        'weight_kg': weight_kg,
        'variation_kg': variation_kg,
        'received_at': received_at.isoformat(),
    }
    cache.set(_scale_cache_key(device_id), snapshot, SCALE_CACHE_TTL_SECONDS)
    return JsonResponse({'ok': True, 'received_at': snapshot['received_at']}, status=202)


@farm_access_required
def goat_weight_live(request, goat_id):
    """Return the latest transient scale state for an explicitly selected goat."""
    goat = get_object_or_404(Goat, goat_id=goat_id)
    return JsonResponse({
        'ok': True,
        'selected_goat': {'goat_id': goat.goat_id, 'name': goat.name},
        **_current_scale_state(),
    })


@farm_owner_required
@require_POST
def save_goat_weight(request, goat_id):
    """Persist a confirmed load-cell or manual measurement for this goat."""
    goat = get_object_or_404(Goat, goat_id=goat_id)
    payload = _read_json_request(request)
    if payload is None:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON payload.'}, status=400)

    source = payload.get('source')
    if source not in {GoatWeightMeasurement.SOURCE_LOAD_CELL, GoatWeightMeasurement.SOURCE_MANUAL}:
        return JsonResponse({'ok': False, 'error': 'Choose Load Cell or Manual Entry.'}, status=400)

    request_id = payload.get('request_id')
    try:
        request_uuid = uuid.UUID(str(request_id)) if request_id else uuid.uuid4()
    except (AttributeError, TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid save request ID.'}, status=400)

    existing = GoatWeightMeasurement.objects.filter(request_id=request_uuid).select_related('goat').first()
    if existing:
        if existing.goat_id != goat.pk:
            return JsonResponse({'ok': False, 'error': 'This save request belongs to another goat.'}, status=409)
        return JsonResponse(_measurement_payload(existing, duplicate=True))

    device_id = ''
    measured_at = timezone.now()
    if source == GoatWeightMeasurement.SOURCE_LOAD_CELL:
        scale = _current_scale_state()
        if not scale.get('connected'):
            return JsonResponse({'ok': False, 'error': 'Scale is offline. Use Manual Entry or try again.'}, status=409)
        if not scale.get('hx711_ready') or not scale.get('valid'):
            return JsonResponse({'ok': False, 'error': 'The HX711 reading is unavailable or invalid.'}, status=409)
        if not scale.get('weight_detected'):
            return JsonResponse({'ok': False, 'error': 'No goat weight is detected on the platform.'}, status=409)
        if not scale.get('stable'):
            return JsonResponse({'ok': False, 'error': 'Wait until the weight is stable before saving.'}, status=409)
        raw_weight = scale.get('weight_kg')
        device_id = scale.get('device_id', SCALE_DEVICE_ID)
        measured_at = parse_datetime(scale.get('received_at', '')) or measured_at
    else:
        raw_weight = payload.get('weight_kg')

    try:
        weight_kg = Decimal(str(raw_weight)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Enter a valid numeric weight.'}, status=400)
    if not weight_kg.is_finite() or not MIN_GOAT_WEIGHT_KG <= weight_kg <= MAX_GOAT_WEIGHT_KG:
        return JsonResponse({'ok': False, 'error': 'Weight must be between 0.10 and 300.00 kg.'}, status=400)

    try:
        with transaction.atomic():
            measurement = GoatWeightMeasurement.objects.create(
                goat=goat,
                weight_kg=weight_kg,
                source=source,
                measured_at=measured_at,
                recorded_by=request.user,
                device_id=device_id,
                request_id=request_uuid,
            )
            goat.weight_kg = float(weight_kg)
            goat.save(update_fields=['weight_kg', 'last_updated'])
    except IntegrityError:
        existing = GoatWeightMeasurement.objects.filter(request_id=request_uuid).select_related('goat').first()
        if existing and existing.goat_id == goat.pk:
            return JsonResponse(_measurement_payload(existing, duplicate=True))
        raise

    return JsonResponse(_measurement_payload(measurement), status=201)


def _save_data_url_image(goat, data_url, image_type='identification',
                         description='Captured via camera'):
    """Decode a base64 data URL (webcam capture) and store it as a GoatImage.

    Stored exactly like an uploaded image so captured and uploaded photos are
    treated identically. Visual reference only.
    """
    import base64
    import uuid
    from django.core.files.base import ContentFile

    try:
        if ';base64,' in data_url:
            header, encoded = data_url.split(';base64,', 1)
            ext = 'jpg'
            if '/' in header:
                ext = header.split('/')[-1].split(';')[0] or 'jpg'
            if ext == 'jpeg':
                ext = 'jpg'
        else:
            encoded = data_url
            ext = 'jpg'

        image_data = base64.b64decode(encoded, validate=True)
        if len(image_data) > MAX_GOAT_IMAGE_BYTES:
            raise ValidationError('Captured goat photos must be 5 MB or smaller.')
        file_name = f"{goat.goat_id}_{uuid.uuid4().hex[:8]}.{ext}"
        upload = ContentFile(image_data, name=file_name)
        upload.content_type = 'image/png' if ext == 'png' else (
            'image/webp' if ext == 'webp' else 'image/jpeg'
        )
        normalized = _validated_goat_image(upload)

        goat_image = GoatImage(
            goat=goat,
            image_type=image_type if image_type in {
                'profile', 'full_body', 'face', 'identification', 'health', 'training'
            } else 'identification',
            description=description,
        )
        goat_image.image.save(normalized.name, normalized, save=True)
        return goat_image
    except Exception as exc:
        logger.error(f"Failed to save captured photo for {goat.goat_id}: {exc}")
        return None


@farm_access_required
def goat_inventory(request):
    """
    Modern livestock inventory: list, search, filter, and manage goats.

    Livestock record management only — no AI/detection/alert data.
    """
    # Get filter parameters
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '')

    # Base queryset for inventory
    goats = Goat.objects.select_related('ble_beacon').prefetch_related(
        Prefetch(
            'images',
            queryset=GoatImage.objects.order_by('-uploaded_at'),
            to_attr='inventory_images',
        )
    )

    # Apply status filter
    if status_filter != 'all':
        goats = goats.filter(status=status_filter)

    # Apply search
    if search_query:
        goats = goats.filter(
            Q(goat_id__icontains=search_query) |
            Q(name__icontains=search_query)
        )

    goats = goats.order_by('-date_added')

    # Attach cover image for each goat (newest image acts as the cover)
    for goat in goats:
        goat.latest_image = goat.inventory_images[0] if goat.inventory_images else None

    # Statistics
    total_goats = Goat.objects.count()
    active_goats = Goat.objects.filter(status='active').count()
    sold_goats = Goat.objects.filter(status='sold').count()
    dead_goats = Goat.objects.filter(status='dead').count()
    missing_goats_count = Goat.objects.filter(status='missing').count()

    context = {
        # Inventory data
        'goats': goats,
        'total_goats': total_goats,
        'active_goats': active_goats,
        'sold_goats': sold_goats,
        'dead_goats': dead_goats,
        'missing_goats_count': missing_goats_count,
        'status_filter': status_filter,
        'search_query': search_query,

        'page_title': 'Goat Inventory'
    }

    return render(request, 'iot/goat_inventory.html', context)


@farm_access_required
def goat_detail_enhanced(request, goat_id):
    """
    Modern goat management page: view & edit all livestock information,
    manage vaccination records, and manage the image gallery.

    Livestock record management only — no AI/detection data is shown here.
    """
    goat = get_object_or_404(Goat, goat_id=goat_id)
    beacon = getattr(goat, 'ble_beacon', None)

    if request.method == 'POST':
        if not can_manage_farm(request.user):
            raise PermissionDenied('Farm Operators cannot modify goat records.')
        form = GoatForm(request.POST, instance=goat)
        form.fields.pop('weight_kg', None)
        beacon_form = BLEBeaconForm(request.POST, instance=beacon, prefix='ble')
        goat_valid = form.is_valid()
        beacon_valid = beacon_form.is_valid()
        if goat_valid and beacon_valid:
            with transaction.atomic():
                updated = form.save()
                beacon = beacon_form.save_for_goat(updated)

                # Save any webcam-captured photos submitted alongside the form.
                # The template packs one or more data URLs into a JSON array.
                captured_raw = request.POST.get('captured_photos', '').strip()
                if captured_raw:
                    try:
                        captured_list = json.loads(captured_raw)
                        if isinstance(captured_list, str):
                            captured_list = [captured_list]
                    except (ValueError, TypeError):
                        captured_list = [captured_raw]
                    for data_url in captured_list:
                        if data_url:
                            _save_data_url_image(
                                updated, data_url,
                                description='Captured via camera',
                            )

                # Save verified, normalized uploads only. Browser MIME claims
                # are not trusted and executable/polyglot tails are discarded.
                for image_file in request.FILES.getlist('images'):
                    try:
                        normalized = _validated_goat_image(image_file)
                    except ValidationError as exc:
                        messages.error(request, exc.messages[0])
                        continue
                    GoatImage.objects.create(
                        goat=updated,
                        image=normalized,
                        image_type='identification',
                        description='Uploaded via manage page',
                    )

            messages.success(request, f'Changes saved for {updated.goat_id}.')
            return redirect('iot:goat_detail_enhanced', goat_id=updated.goat_id)
        else:
            messages.error(request, 'Please correct the errors highlighted below.')
    else:
        form = GoatForm(instance=goat)
        form.fields.pop('weight_kg', None)
        beacon_form = BLEBeaconForm(instance=beacon, prefix='ble')
        if not can_manage_farm(request.user):
            for field in form.fields.values():
                field.disabled = True
            for field in beacon_form.fields.values():
                field.disabled = True

    # Image gallery — newest first; the newest image acts as the cover/primary.
    images = GoatImage.objects.filter(goat=goat).order_by('-uploaded_at')
    cover_image = images.first()
    tracking_state = None
    if beacon:
        tracking_state = beacon.tracking_states.select_related(
            'receiver__device'
        ).order_by('-last_seen').first()

    context = {
        'goat': goat,
        'form': form,
        'beacon': beacon,
        'beacon_form': beacon_form,
        'tracking_state': tracking_state,
        'images': images,
        'cover_image': cover_image,
        'image_count': images.count(),
        'weight_history': goat.weight_measurements.select_related('recorded_by').all(),
        'page_title': f'Manage: {goat.goat_id}',
    }

    return render(request, 'iot/goat_detail_enhanced.html', context)


@farm_owner_required
@require_POST
def delete_goat_image(request, goat_id, image_id):
    """Delete a single image from a goat's gallery (Goat Inventory module)."""
    goat = get_object_or_404(Goat, goat_id=goat_id)
    image = get_object_or_404(GoatImage, id=image_id, goat=goat)
    image.delete()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'image_id': image_id})

    messages.success(request, 'Image deleted.')
    return redirect('goat_detail_enhanced', goat_id=goat_id)


@farm_owner_required
@require_POST
def upload_goat_image(request, goat_id):
    """
    Upload and store a goat gallery image.
    """
    goat = get_object_or_404(Goat, goat_id=goat_id)

    image_file = request.FILES.get('image')
    image_type = request.POST.get('image_type', 'identification')
    description = request.POST.get('description', '').strip()
    is_training_data = request.POST.get('is_training_data') == 'on'

    valid_image_types = {
        'profile', 'full_body', 'face', 'identification', 'health', 'training'
    }

    if not image_file:
        messages.error(request, 'Please select an image to upload.')
        return redirect('goat_detail_enhanced', goat_id=goat_id)

    if image_type not in valid_image_types:
        image_type = 'identification'

    try:
        normalized = _validated_goat_image(image_file)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect('goat_detail_enhanced', goat_id=goat_id)

    GoatImage.objects.create(
        goat=goat,
        image=normalized,
        image_type=image_type,
        description=description,
        is_training_data=is_training_data,
    )

    messages.success(request, f'Image uploaded successfully for {goat.goat_id}.')
    return redirect('goat_detail_enhanced', goat_id=goat_id)


@farm_owner_required
@require_POST
def update_goat_status(request, goat_id):
    """
    Update goat status (Active/Sold/Dead/Missing).
    Phase 5: Status management
    """
    goat = get_object_or_404(Goat, goat_id=goat_id)
    
    new_status = request.POST.get('status')
    notes = request.POST.get('notes', '')
    
    if new_status not in ['active', 'sold', 'dead', 'missing']:
        messages.error(request, 'Invalid status value.')
        return redirect('goat_detail_enhanced', goat_id=goat_id)
    
    old_status = goat.status
    goat.status = new_status
    goat.save()
    
    # Log status change
    logger.info(f"Goat {goat_id} status changed from '{old_status}' to '{new_status}' by {request.user.username}")
    
    # If marked as missing, check if there's an active alert
    if new_status == 'missing':
        # Don't auto-create alert here, let AI detection handle it
        messages.warning(request, f'Goat {goat_id} marked as missing. System will monitor for detection.')
    
    # If found (missing → active), resolve alerts
    if old_status == 'missing' and new_status == 'active':
        alerts = MissingGoatAlert.objects.filter(
            missing_goats=goat,
            is_resolved=False
        )
        for alert in alerts:
            # Check if all goats in this alert are now active
            missing_count = alert.missing_goats.exclude(status='active').count()
            if missing_count == 0:
                alert.is_resolved = True
                alert.resolved_at = timezone.now()
                alert.resolution_notes = f"Goat {goat_id} found and marked active by {request.user.username}"
                alert.save()
                messages.success(request, f'Alert #{alert.id} automatically resolved.')
    
    # Add notes if provided
    if notes:
        # Could create a GoatNote model to track status change notes
        pass
    
    messages.success(request, f'Goat {goat_id} status updated to {new_status.upper()}.')
    
    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': f'Status updated to {new_status}',
            'old_status': old_status,
            'new_status': new_status
        })
    
    return redirect('goat_detail_enhanced', goat_id=goat_id)


@farm_owner_required
def missing_goat_alerts(request):
    """
    View all missing goat alerts.
    Phase 5: Alert management
    """
    # Get filter parameters
    show_resolved = request.GET.get('show_resolved', 'false') == 'true'
    severity_filter = request.GET.get('severity', 'all')
    
    # Base queryset
    alerts = MissingGoatAlert.objects.all()
    
    # Apply filters
    if not show_resolved:
        alerts = alerts.filter(is_resolved=False)
    
    if severity_filter != 'all':
        alerts = alerts.filter(severity=severity_filter)
    
    alerts = alerts.order_by('-triggered_at').select_related()
    
    # Add missing goat details
    for alert in alerts:
        alert.missing_goat_list = alert.missing_goats.all()
        if alert.is_resolved and alert.resolved_at:
            time_to_resolve = alert.resolved_at - alert.triggered_at
            alert.resolution_time = format_time_duration(time_to_resolve)
        else:
            alert.resolution_time = None
    
    # Statistics
    total_alerts = MissingGoatAlert.objects.count()
    active_alerts = MissingGoatAlert.objects.filter(is_resolved=False).count()
    resolved_alerts = MissingGoatAlert.objects.filter(is_resolved=True).count()
    
    high_severity = MissingGoatAlert.objects.filter(severity='high', is_resolved=False).count()
    
    context = {
        'alerts': alerts,
        'total_alerts': total_alerts,
        'active_alerts': active_alerts,
        'resolved_alerts': resolved_alerts,
        'high_severity': high_severity,
        'show_resolved': show_resolved,
        'severity_filter': severity_filter,
        'page_title': 'Missing Goat Alerts'
    }
    
    return render(request, 'iot/missing_goat_alerts.html', context)


@farm_owner_required
@require_POST
def resolve_alert(request, alert_id):
    """
    Manually resolve a missing goat alert.
    Phase 5: Alert management
    """
    alert = get_object_or_404(MissingGoatAlert, id=alert_id)
    
    if alert.is_resolved:
        messages.info(request, 'Alert is already resolved.')
    else:
        notes = request.POST.get('notes', '')
        alert.resolve(notes=notes or f"Manually resolved by {request.user.username}")
        messages.success(request, f'Alert #{alert_id} has been resolved.')
        logger.info(f"Alert #{alert_id} manually resolved by {request.user.username}")
    
    # Return JSON for AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': 'Alert resolved',
            'alert_id': alert_id
        })
    
    return redirect('missing_goat_alerts')


@farm_access_required
def detection_history(request):
    """
    View recent detection history across all goats.
    Phase 5: Detection timeline
    """
    # Get filter parameters
    try:
        hours = int(request.GET.get('hours', '24'))
    except (TypeError, ValueError):
        hours = 24
    hours = min(max(hours, 1), 168)
    camera_id = request.GET.get('camera', 'all')
    goat_id = request.GET.get('goat', 'all')
    
    # Base queryset
    cutoff_time = timezone.now() - timedelta(hours=hours)
    detections = GoatDetectionHistory.objects.filter(
        timestamp__gte=cutoff_time
    ).select_related('goat', 'camera').order_by('-timestamp')
    
    # Apply filters
    if camera_id != 'all':
        detections = detections.filter(camera_id=camera_id)
    
    if goat_id != 'all':
        detections = detections.filter(goat__goat_id=goat_id)
    
    # Statistics
    total_detections = detections.count()
    unique_goats = detections.values('goat').distinct().count()
    avg_confidence = detections.aggregate(avg=Avg('detection_confidence'))['avg'] or 0
    
    # Get available cameras and goats for filters
    from .goat_models import IPCamera
    cameras = IPCamera.objects.filter(is_active=True)
    goats = Goat.objects.filter(status='active').order_by('goat_id')
    
    context = {
        'detections': detections[:100],  # Limit to 100 most recent
        'total_detections': total_detections,
        'unique_goats': unique_goats,
        'avg_confidence': avg_confidence,
        'cameras': cameras,
        'goats': goats,
        'hours': hours,
        'camera_id': camera_id,
        'goat_id': goat_id,
        'page_title': 'Detection History'
    }
    
    return render(request, 'iot/detection_history.html', context)




def format_time_duration(time_diff):
    """Format a timedelta into human-readable duration string."""
    seconds = time_diff.total_seconds()
    
    if seconds < 60:
        return f"{int(seconds)} seconds"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"
    else:
        days = int(seconds / 86400)
        hours = int((seconds % 86400) / 3600)
        return f"{days}d {hours}h"
