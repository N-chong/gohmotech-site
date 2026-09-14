from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError as ApiValidationError
from marketplace.auth import is_admin
from marketplace.decorators import farm_access_required, farm_owner_required, staff_required
from marketplace.permissions import FarmRolePermission, IsAdmin, IsFarmOwnerOrAdmin
from django.utils import timezone
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db import transaction
from django.db.models import Avg, Max, Min, Count, Q, Sum
from datetime import timedelta
import logging
import json

logger = logging.getLogger(__name__)
from .models import Device, SensorData, Alert, ActuatorState, AutomationRule, ActuationLog, SensorReading
from .serializers import (
    DeviceSerializer, SensorDataSerializer, AlertSerializer,
    ActuatorStateSerializer, AutomationRuleSerializer, ActuationLogSerializer,
    SensorReadingSerializer
)
from .forms import BLEBeaconForm, GoatForm
from .ble_services import build_tracking_snapshot
from .weather_service import get_farm_weather
from .status_utils import (
    is_device_online, controller_status, system_status,
)
from .device_authentication import HasLegacyDeviceKey
from .goat_photos import photo_slots, prepared_standard_photos, save_standard_photo


def _bounded_hours(request, default=24, maximum=168):
    """Parse a bounded history window without allowing 500s or unbounded reads."""
    raw_value = request.query_params.get('hours', default)
    try:
        hours = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ApiValidationError({'hours': 'Enter a whole number of hours.'}) from exc
    if not 1 <= hours <= maximum:
        raise ApiValidationError({'hours': f'Hours must be between 1 and {maximum}.'})
    return hours

try:
    from .goat_models import Goat, GoatImage, GoatBehaviorLog, GrassHealthLog, IPCamera
except ImportError:
    Goat = None
    GoatImage = None
    GoatBehaviorLog = None
    GrassHealthLog = None
    IPCamera = None

try:
    from feeding.models import AutomatedFeedingConfig, FeedSchedule, FeedLevel
except ImportError:
    AutomatedFeedingConfig = None
    FeedSchedule = None
    FeedLevel = None

try:
    from ml_models.models import Detection
except ImportError:
    Detection = None


class DeviceViewSet(viewsets.ModelViewSet):
    """ViewSet for Device CRUD operations"""
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    permission_classes = [IsAdmin]
    
    @action(detail=True, methods=['get'])
    def recent_data(self, request, pk=None):
        """Get recent sensor data for a device"""
        device = self.get_object()
        hours = _bounded_hours(request)
        since = timezone.now() - timedelta(hours=hours)
        
        data = SensorData.objects.filter(
            device=device,
            timestamp__gte=since
        ).order_by('-timestamp')[:1000]
        serializer = SensorDataSerializer(data, many=True)
        return Response(serializer.data)


class SensorDataViewSet(viewsets.ModelViewSet):
    """ViewSet for Sensor Data operations"""
    queryset = SensorData.objects.all()
    serializer_class = SensorDataSerializer
    permission_classes = [FarmRolePermission]
    filterset_fields = ['device', 'sensor_type', 'timestamp']
    
    def create(self, request, *args, **kwargs):
        """Create sensor data and check for anomalies"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        # Here you can add ML-based anomaly detection
        # sensor_data = serializer.instance
        # check_anomaly(sensor_data)
        
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class AlertViewSet(viewsets.ModelViewSet):
    """ViewSet for Alert operations"""
    queryset = Alert.objects.all()
    serializer_class = AlertSerializer
    permission_classes = [IsFarmOwnerOrAdmin]
    filterset_fields = ['device', 'severity', 'is_resolved']

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Mark an alert as resolved and resolve its linked notification, if any."""
        alert = self.get_object()
        alert.is_resolved = True
        alert.resolved_at = timezone.now()
        alert.save(update_fields=['is_resolved', 'resolved_at'])

        # Keep the unified inbox in sync: resolve the notification backing this
        # event, if one exists. Best-effort — never block alert resolution on it.
        try:
            from django.contrib.contenttypes.models import ContentType
            from security.models import Notification
            ct = ContentType.objects.get_for_model(Alert)
            notification = Notification.objects.filter(
                source_content_type=ct, source_object_id=alert.pk
            ).first()
            if notification:
                notification.resolve(user=request.user)
        except Exception:
            pass

        serializer = self.get_serializer(alert)
        return Response(serializer.data)


class SensorReadingViewSet(viewsets.ModelViewSet):
    """ViewSet for Environmental Sensor Readings (Temperature, Humidity, etc.)"""
    queryset = SensorReading.objects.all()
    serializer_class = SensorReadingSerializer
    filterset_fields = ['device', 'timestamp']
    
    def get_permissions(self):
        """Require the device key for ESP32 writes and farm RBAC for reads."""
        if self.action == 'create':
            return [HasLegacyDeviceKey()]
        return [FarmRolePermission()]
    
    def create(self, request, *args, **kwargs):
        """Create sensor reading from ESP32 device"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        # Log the reading
        reading = serializer.instance
        logger.info(
            "Sensor reading saved: %s - Temp: %s C, Humidity: %s%%, Light: %s%%, MQ-135 raw: %s",
            reading.device.name,
            reading.temperature,
            reading.humidity,
            reading.light_level_percentage,
            reading.air_quality_raw,
        )
        
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get latest sensor readings for all devices"""
        devices = Device.objects.filter(is_active=True)
        latest_readings = []
        
        for device in devices:
            latest = SensorReading.objects.filter(device=device).order_by('-timestamp').first()
            if latest:
                serializer = self.get_serializer(latest)
                latest_readings.append(serializer.data)
        
        return Response(latest_readings)
    
    @action(detail=False, methods=['get'])
    def device_history(self, request):
        """Get sensor reading history for a specific device"""
        device_id = request.query_params.get('device_id')
        hours = _bounded_hours(request)
        
        if not device_id:
            return Response({"error": "device_id parameter required"}, status=400)
        
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response({"error": "Device not found"}, status=404)
        
        since = timezone.now() - timedelta(hours=hours)
        readings = SensorReading.objects.filter(
            device=device,
            timestamp__gte=since
        ).order_by('-timestamp')[:1000]
        
        serializer = self.get_serializer(readings, many=True)
        return Response(serializer.data)


# ============ Client-Facing Views ============


def build_recent_activity(limit=12):
    """Merge recent real events from several sources into one time-ordered feed.

    Pulls from ActuationLog, FeedLog, Detection, Alert and MissingGoatAlert —
    every source that actually gets written by the running system — and returns
    a list of plain dicts the dashboard template can render directly. Each source
    is guarded independently so one empty/missing table never breaks the feed,
    and nothing is fabricated: an empty system yields an empty list.
    """
    items = []

    # --- Actuator commands / state changes ---
    try:
        for log in ActuationLog.objects.select_related('device').order_by('-timestamp')[:limit]:
            action = getattr(log, 'action', '')
            icon = {
                'open': 'bi-door-open', 'close': 'bi-door-closed',
                'turn_on': 'bi-lightbulb', 'turn_off': 'bi-lightbulb-off',
            }.get(action, 'bi-robot')
            tone = {'failed': 'danger', 'queued': 'warning'}.get(
                getattr(log, 'result', ''), 'muted')
            device_name = getattr(getattr(log, 'device', None), 'name', 'Device')
            detail = log.get_source_display() if hasattr(log, 'get_source_display') else ''
            if getattr(log, 'triggered_by', ''):
                detail = f"{detail} · {log.triggered_by}" if detail else log.triggered_by
            items.append({
                'timestamp': log.timestamp,
                'icon': icon,
                'tone': tone,
                'title': f"{device_name}: {log.get_action_display()}",
                'detail': detail,
            })
    except Exception:
        logger.debug("recent_activity: ActuationLog source unavailable", exc_info=True)

    # --- Feeding events ---
    try:
        from feeding.models import FeedLog
        for fl in FeedLog.objects.select_related('feeder').order_by('-timestamp')[:limit]:
            tone = {'failed': 'danger', 'partial': 'warning', 'pending': 'info'}.get(
                getattr(fl, 'status', ''), 'success')
            feeder_name = getattr(getattr(fl, 'feeder', None), 'name', 'Feeder')
            items.append({
                'timestamp': fl.timestamp,
                'icon': 'bi-basket',
                'tone': tone,
                'title': f"{feeder_name} dispensed {fl.amount_dispensed}g",
                'detail': fl.get_feeding_mode_display() if hasattr(fl, 'get_feeding_mode_display') else '',
            })
    except Exception:
        logger.debug("recent_activity: FeedLog source unavailable", exc_info=True)

    # --- Camera detections ---
    try:
        if Detection:
            for det in Detection.objects.order_by('-timestamp')[:limit]:
                conf = getattr(det, 'confidence', None)
                detail = f"{conf:.0%} confidence" if conf else ''
                items.append({
                    'timestamp': det.timestamp,
                    'icon': 'bi-camera-video',
                    'tone': 'info',
                    'title': f"{det.goat_count} goat(s) seen by camera",
                    'detail': detail,
                })
    except Exception:
        logger.debug("recent_activity: Detection source unavailable", exc_info=True)

    # --- IoT alerts ---
    try:
        for al in Alert.objects.select_related('device').order_by('-created_at')[:limit]:
            tone = {'critical': 'danger', 'high': 'warning'}.get(
                getattr(al, 'severity', ''), 'info')
            items.append({
                'timestamp': al.created_at,
                'icon': 'bi-exclamation-triangle',
                'tone': tone,
                'title': (al.message or 'Sensor alert')[:80],
                'detail': f"{al.get_severity_display()} alert",
            })
    except Exception:
        logger.debug("recent_activity: Alert source unavailable", exc_info=True)

    # --- Missing-goat alerts ---
    try:
        from .goat_models import MissingGoatAlert
        for mg in MissingGoatAlert.objects.order_by('-triggered_at')[:limit]:
            tone = {'critical': 'danger', 'high': 'warning'}.get(
                getattr(mg, 'severity', ''), 'warning')
            items.append({
                'timestamp': mg.triggered_at,
                'icon': 'bi-search',
                'tone': tone,
                'title': mg.title or 'Missing goat alert',
                'detail': f"{mg.missing_count} missing" if getattr(mg, 'missing_count', None) else '',
            })
    except Exception:
        logger.debug("recent_activity: MissingGoatAlert source unavailable", exc_info=True)

    # Newest first; drop any without a usable timestamp.
    items = [i for i in items if i.get('timestamp') is not None]
    items.sort(key=lambda i: i['timestamp'], reverse=True)
    return items[:limit]


@farm_access_required
def dashboard_modern(request):
    if not is_admin(request.user):
        return redirect('iot:owner_dashboard')
    """Modern dashboard with farm map visualization"""
    devices = Device.objects.filter(is_active=True)[:8]  # Show first 8 active devices
    alerts = Alert.objects.filter(is_resolved=False).order_by('-created_at')[:5]
    
    # Add severity class for badge colors
    for alert in alerts:
        if alert.severity == 'critical':
            alert.severity_class = 'danger'
        elif alert.severity == 'high':
            alert.severity_class = 'warning'
        else:
            alert.severity_class = 'info'
    
    # Get environmental data (last hour)
    one_hour_ago = timezone.now() - timedelta(hours=1)
    recent_data = SensorData.objects.filter(timestamp__gte=one_hour_ago)
    
    # Get latest Kamotech ESP32 sensor readings (DHT21)
    kamotech_device = Device.objects.filter(device_id='kamotech_esp32_001').first()
    latest_sensor_reading = None
    if kamotech_device:
        latest_sensor_reading = SensorReading.objects.filter(device=kamotech_device).order_by('-timestamp').first()
    
    # Use Kamotech ESP32 data if available, otherwise fall back to old SensorData
    if latest_sensor_reading and latest_sensor_reading.temperature and latest_sensor_reading.humidity:
        temp_avg = latest_sensor_reading.temperature
        humidity_avg = latest_sensor_reading.humidity
    else:
        # Calculate averages from old SensorData model
        temp_avg = recent_data.filter(sensor_type='temperature').aggregate(avg=Avg('value'))['avg']
        humidity_avg = recent_data.filter(sensor_type='humidity').aggregate(avg=Avg('value'))['avg']
    
    soil_avg = recent_data.filter(sensor_type='soil_moisture').aggregate(avg=Avg('value'))['avg']
    
    # Livestock statistics (honest inventory aggregates — always populated)
    total_goats = 0
    healthy_goats = 0
    monitoring_goats = 0
    sick_goats = 0
    quarantine_goats = 0
    missing_goats = 0
    vaccinations_due = 0
    if Goat:
        active_qs = Goat.objects.filter(is_active=True)
        counts = active_qs.aggregate(
            total=Count('id'),
            healthy=Count('id', filter=Q(health_status='healthy')),
            monitoring=Count('id', filter=Q(health_status='monitoring')),
            sick=Count('id', filter=Q(health_status='sick')),
            quarantine=Count('id', filter=Q(health_status='quarantine')),
            missing=Count('id', filter=Q(status='missing')),
        )
        total_goats = counts['total'] or 0
        healthy_goats = counts['healthy'] or 0
        monitoring_goats = counts['monitoring'] or 0
        sick_goats = counts['sick'] or 0
        quarantine_goats = counts['quarantine'] or 0
        missing_goats = counts['missing'] or 0
        # Vaccinations overdue or coming due within 30 days.
        soon = timezone.localdate() + timedelta(days=30)
        vaccinations_due = active_qs.filter(
            next_due_date__isnull=False, next_due_date__lte=soon
        ).count()

    # Real active-alert count (replaces the fake `default:3` in the template).
    active_alert_count = Alert.objects.filter(is_resolved=False).count()

    # Derived system status: controller online (sensor activity), camera, model.
    sys_status = system_status()

    # Current actuator desired-states for the automation summary row.
    actuators = {}
    try:
        for a in ActuatorState.objects.select_related('device'):
            actuators[a.actuator_type] = a
    except Exception:
        logger.debug("dashboard: ActuatorState unavailable", exc_info=True)

    
    # Auto-feed status
    auto_feed_enabled = False
    active_schedules = 0
    if AutomatedFeedingConfig:
        config = AutomatedFeedingConfig.get_config()
        auto_feed_enabled = config.is_enabled
    if FeedSchedule:
        active_schedules = FeedSchedule.objects.filter(is_active=True).count()
    
    # Get single active camera (only one camera used for goat house monitoring)
    camera = None
    if IPCamera:
        camera = IPCamera.objects.filter(is_active=True).first()
    
    # Latest goat detection count (for real-time dashboard)
    latest_goat_count = None
    latest_detection_time = None
    if Detection:
        latest_detection = Detection.objects.order_by('-timestamp').first()
        if latest_detection:
            latest_goat_count = latest_detection.goat_count
            latest_detection_time = latest_detection.timestamp
    
    # Feeder level (for real-time dashboard)
    feed_level_percent = None
    feed_total_grams = 0
    feed_capacity_grams = 0
    feed_level_time = None
    if FeedLevel:
        feed_levels = FeedLevel.objects.all()
        if feed_levels.exists():
            feed_aggregate = feed_levels.aggregate(
                total=Sum('current_level_grams'),
                capacity=Sum('capacity_grams'),
                latest=Max('updated_at')
            )
            feed_total_grams = feed_aggregate['total'] or 0
            feed_capacity_grams = feed_aggregate['capacity'] or 0
            feed_level_time = feed_aggregate['latest']
            if feed_capacity_grams > 0:
                feed_level_percent = (feed_total_grams / feed_capacity_grams) * 100

    weather_info = get_farm_weather()
    ble_tracking = build_tracking_snapshot()

    controller = sys_status.get('controller', {})
    camera_status = sys_status.get('camera', {})
    active_model = sys_status.get('active_model')

    context = {
        'devices': devices,
        'alerts': alerts,
        'active_alert_count': active_alert_count,
        'avg_temperature': round(temp_avg, 1) if temp_avg else None,
        'avg_humidity': round(humidity_avg, 1) if humidity_avg else None,
        'avg_soil_moisture': round(soil_avg, 1) if soil_avg else None,
        'latest_sensor_reading': latest_sensor_reading,  # Kamotech ESP32 data
        # Livestock (honest aggregates)
        'total_goats': total_goats,
        'healthy_goats': healthy_goats,
        'monitoring_goats': monitoring_goats,
        'sick_goats': sick_goats,
        'quarantine_goats': quarantine_goats,
        'missing_goats': missing_goats,
        'vaccinations_due': vaccinations_due,
        # Automation summary
        'actuators': actuators,
        'auto_feed_enabled': auto_feed_enabled,
        'active_schedules': active_schedules,
        # System status (derived, real)
        'controller_online': controller.get('online', False),
        'controller_configured': controller.get('configured', False),
        'controller_last_seen': controller.get('last_seen'),
        'camera': camera,
        'camera_status': camera_status,
        'active_model': active_model,
        # Detection (clearly a camera reading, not inventory)
        'latest_goat_count': latest_goat_count,
        'latest_detection_time': latest_detection_time,
        # Feeder
        'feed_level_percent': round(feed_level_percent, 1) if feed_level_percent is not None else None,
        'feed_total_grams': feed_total_grams,
        'feed_capacity_grams': feed_capacity_grams,
        'feed_level_time': feed_level_time,
        'weather_info': weather_info,
        # Merged real-event feed
        'recent_activity': build_recent_activity(),
        'ble_tracking_summary': ble_tracking['summary'],
        'ble_receivers': ble_tracking['receivers'],
        'page_title': 'KaMoTech Dashboard'
    }
    return render(request, 'iot/dashboard_modern.html', context)


@farm_access_required
def goats_list(request):
    """Display list of all goats"""
    if Goat is None:
        return render(request, 'iot/error.html', {'message': 'Goat models not available'})
    
    goats = Goat.objects.filter(is_active=True).select_related().order_by('name')
    
    # Statistics
    total_goats = goats.count()
    healthy_goats = goats.filter(health_status='healthy').count()
    sick_goats = goats.filter(health_status='sick').count()
    
    context = {
        'goats': goats,
        'total_goats': total_goats,
        'healthy_goats': healthy_goats,
        'sick_goats': sick_goats,
        'page_title': 'Goat Inventory'
    }
    return render(request, 'iot/goats_list.html', context)


@farm_access_required
def goat_detail(request, goat_id):
    """Display detailed information about a specific goat"""
    if Goat is None:
        return render(request, 'iot/error.html', {'message': 'Goat models not available'})
    
    goat = get_object_or_404(Goat, goat_id=goat_id)
    
    # Get related data
    images = GoatImage.objects.filter(goat=goat).order_by('-uploaded_at')[:10] if GoatImage else []
    behaviors = GoatBehaviorLog.objects.filter(goat=goat).order_by('-timestamp')[:20] if GoatBehaviorLog else []
    
    # Behavior statistics
    if GoatBehaviorLog:
        behavior_stats = GoatBehaviorLog.objects.filter(goat=goat).values('behavior_type').annotate(
            count=Count('id'),
            avg_confidence=Avg('confidence_score')
        )
    else:
        behavior_stats = []
    
    context = {
        'goat': goat,
        'images': images,
        'behaviors': behaviors,
        'behavior_stats': behavior_stats,
        'page_title': f'Goat: {goat.name}'
    }
    return render(request, 'iot/goat_detail.html', context)


@farm_owner_required
def add_goat(request):
    """Add a new goat to the inventory (manual registration only)"""
    if Goat is None:
        return render(request, 'iot/error.html', {'message': 'Goat models not available'})

    if request.method == 'POST':
        form = GoatForm(request.POST)
        beacon_form = BLEBeaconForm(request.POST, prefix='ble')
        goat_valid = form.is_valid()
        beacon_valid = beacon_form.is_valid()
        prepared_photos, photo_errors = prepared_standard_photos(request)
        if goat_valid and beacon_valid and not photo_errors:
            with transaction.atomic():
                goat = form.save(commit=False)
                goat.owner = request.user
                goat.record_source = Goat.SMART_FARM
                goat.save()
                beacon_form.save_for_goat(goat)

                # Save webcam-captured photo as a reference image (not used for AI recognition)
                captured_photo = form.cleaned_data.get('captured_photo', '')
                if captured_photo and GoatImage is not None:
                    _save_captured_photo(goat, captured_photo)
                for angle, normalized in prepared_photos.items():
                    save_standard_photo(goat, angle, normalized)

            messages.success(request, f'Goat "{goat.goat_id}" has been added successfully!')
            return redirect('iot:goat_detail_enhanced', goat_id=goat.goat_id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = GoatForm()
        beacon_form = BLEBeaconForm(prefix='ble')
        photo_errors = {}

    context = {
        'form': form,
        'beacon_form': beacon_form,
        'photo_slots': photo_slots(errors=photo_errors),
        'photo_errors': photo_errors,
        'page_title': 'Add New Goat'
    }
    return render(request, 'iot/add_goat.html', context)


def _save_captured_photo(goat, data_url):
    """Decode a base64 data URL from the webcam and store it as a GoatImage.

    This image is a visual reference only — it is NOT processed for AI recognition.
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

        image_data = base64.b64decode(encoded)
        file_name = f"{goat.goat_id}_{uuid.uuid4().hex[:8]}.{ext}"

        goat_image = GoatImage(
            goat=goat,
            image_type='profile',
            description='Reference photo captured via webcam during manual registration',
            is_primary=not GoatImage.objects.filter(goat=goat, is_primary=True).exists(),
        )
        goat_image.image.save(file_name, ContentFile(image_data), save=True)
        return goat_image
    except Exception as exc:
        logger.error(f"Failed to save captured webcam photo for {goat.goat_id}: {exc}")
        return None


@staff_required
def devices_list(request):
    """Display list of all IoT devices"""
    devices = Device.objects.all().order_by('-is_active', 'name')
    
    # Get latest sensor reading for each device
    for device in devices:
        device.latest_reading = SensorData.objects.filter(device=device).order_by('-timestamp').first()
    
    # Statistics
    total_devices = devices.count()
    active_devices = devices.filter(is_active=True).count()
    inactive_devices = total_devices - active_devices
    
    # Device type breakdown
    device_types = devices.values('device_type').annotate(count=Count('id'))
    
    context = {
        'devices': devices,
        'total_devices': total_devices,
        'active_devices': active_devices,
        'inactive_devices': inactive_devices,
        'device_types': device_types,
        'page_title': 'IoT Devices'
    }
    return render(request, 'iot/devices_list.html', context)


@staff_required
def device_detail(request, device_id):
    """Display detailed information about a specific device"""
    device = get_object_or_404(Device, device_id=device_id)
    
    # Get recent sensor data (last 24 hours)
    since = timezone.now() - timedelta(hours=24)
    sensor_data = SensorData.objects.filter(device=device, timestamp__gte=since).order_by('-timestamp')[:100]
    
    # Get recent alerts
    alerts = Alert.objects.filter(device=device).order_by('-created_at')[:10]
    
    # Sensor statistics
    sensor_stats = SensorData.objects.filter(device=device, timestamp__gte=since).values('sensor_type').annotate(
        avg_value=Avg('value'),
        min_value=Min('value'),
        max_value=Max('value'),
        count=Count('id')
    )
    
    context = {
        'device': device,
        'sensor_data': sensor_data,
        'alerts': alerts,
        'sensor_stats': sensor_stats,
        'page_title': f'Device: {device.name}'
    }
    return render(request, 'iot/device_detail.html', context)


@farm_owner_required
def cameras_list(request):
    """Display list of all cameras"""
    if IPCamera is None:
        return render(request, 'iot/error.html', {'message': 'Camera models not available'})
    
    cameras = IPCamera.objects.all().order_by('-is_active', 'location')
    
    # Statistics
    total_cameras = cameras.count()
    active_cameras = cameras.filter(is_active=True).count()
    inactive_cameras = total_cameras - active_cameras
    online_cameras = cameras.filter(status='active').count()
    
    context = {
        'cameras': cameras,
        'total_cameras': total_cameras,
        'active_cameras': active_cameras,
        'inactive_cameras': inactive_cameras,
        'online_cameras': online_cameras,
        'page_title': 'IP Cameras'
    }
    return render(request, 'iot/cameras_list.html', context)


@farm_owner_required
def camera_detail(request, camera_id):
    """Display detailed view of a specific camera"""
    if IPCamera is None:
        return render(request, 'iot/error.html', {'message': 'Camera models not available'})
    
    camera = get_object_or_404(IPCamera, id=camera_id)
    
    context = {
        'camera': camera,
        'page_title': f'Camera: {camera.name}'
    }
    return render(request, 'iot/camera_detail.html', context)


@farm_access_required
def monitoring_dashboard(request):
    """Main monitoring dashboard showing real-time status of all systems"""
    # Get active devices
    devices = Device.objects.filter(is_active=True)
    
    # Get recent sensor data (last hour)
    one_hour_ago = timezone.now() - timedelta(hours=1)
    recent_data = SensorData.objects.filter(timestamp__gte=one_hour_ago).select_related('device')
    
    # Get latest DHT21 sensor readings (kamotech esp32)
    latest_sensor_reading = None
    kamotech_device = Device.objects.filter(device_id='kamotech_esp32_001').first()
    if kamotech_device:
        latest_sensor_reading = SensorReading.objects.filter(device=kamotech_device).order_by('-timestamp').first()
    
    # Get all latest environmental readings
    latest_environmental_readings = []
    for device in devices.filter(device_type='environmental_sensor'):
        reading = SensorReading.objects.filter(device=device).order_by('-timestamp').first()
        if reading:
            latest_environmental_readings.append(reading)
    
    # Get active alerts
    active_alerts = Alert.objects.filter(is_resolved=False).order_by('-created_at')[:20]
    
    # Environmental conditions (latest readings)
    latest_conditions = {}
    for sensor_type in ['temperature', 'humidity', 'soil_moisture', 'light_intensity']:
        latest = SensorData.objects.filter(sensor_type=sensor_type).order_by('-timestamp').first()
        if latest:
            latest_conditions[sensor_type] = latest
    
    # Grass health status
    if GrassHealthLog:
        latest_grass = GrassHealthLog.objects.order_by('-timestamp').first()
    else:
        latest_grass = None
    
    # Goat activity
    if Goat:
        total_goats = Goat.objects.filter(is_active=True).count()
        healthy_goats = Goat.objects.filter(is_active=True, health_status='healthy').count()
    else:
        total_goats = 0
        healthy_goats = 0
    
    # Goat detection stats
    latest_goat_count = None
    if Detection:
        latest_detection = Detection.objects.order_by('-timestamp').first()
        if latest_detection:
            latest_goat_count = latest_detection.goat_count
    
    # Camera status
    camera = None
    camera_status = 'offline'
    if IPCamera:
        camera = IPCamera.objects.filter(is_active=True).first()
        if camera:
            camera_status = camera.status if hasattr(camera, 'status') else 'online'
    
    # Automation system status
    door_actuators = ActuatorState.objects.filter(actuator_type='door').select_related('device')
    light_actuators = ActuatorState.objects.filter(actuator_type='light').select_related('device')
    
    # Recent automation logs (last 10)
    recent_actuations = ActuationLog.objects.select_related('device').order_by('-timestamp')[:10]
    
    # Feeding system status
    feeding_enabled = False
    feeders_count = 0
    if AutomatedFeedingConfig:
        config = AutomatedFeedingConfig.get_config()
        feeding_enabled = config.is_enabled
    if FeedLevel:
        feeders_count = FeedLevel.objects.count()
    
    # System health score (simple calculation)
    health_score = 100
    if active_alerts.count() > 0:
        health_score -= active_alerts.count() * 5
    if healthy_goats < total_goats and total_goats > 0:
        health_score -= ((total_goats - healthy_goats) / total_goats) * 20
    health_score = max(0, health_score)

    weather_info = get_farm_weather()
    
    context = {
        'devices': devices,
        'recent_data': recent_data[:50],
        'active_alerts': active_alerts,
        'latest_conditions': latest_conditions,
        'latest_sensor_reading': latest_sensor_reading,  # DHT21 data
        'latest_environmental_readings': latest_environmental_readings,  # All environmental sensors
        'latest_grass': latest_grass,
        'total_goats': total_goats,
        'healthy_goats': healthy_goats,
        'latest_goat_count': latest_goat_count,
        'camera': camera,
        'camera_status': camera_status,
        'door_actuators': door_actuators,
        'light_actuators': light_actuators,
        'recent_actuations': recent_actuations,
        'feeding_enabled': feeding_enabled,
        'feeders_count': feeders_count,
        'health_score': health_score,
        'weather_info': weather_info,
        'page_title': 'System Monitoring'
    }
    return render(request, 'iot/monitoring_dashboard.html', context)


# ==================== Camera Streaming Views ====================

from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from .goat_models import IPCamera
from .camera_utils import camera_manager
import time


def generate_mjpeg_stream(camera_id, quality=85, fps=20):
    """
    Generator function for MJPEG streaming
    
    Yields JPEG frames in multipart/x-mixed-replace format
    Optimized for real-time, low-latency streaming
    
    Args:
        camera_id: ID of the camera to stream
        
    Yields:
        bytes: MJPEG frame data
    """
    stream = camera_manager.get_stream(camera_id)
    
    if not stream:
        # Return a blank/error frame
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n\r\n'
        return
    
    last_frame_time = time.time()
    frame_count = 0
    
    quality = int(max(40, min(95, quality)))
    fps = max(1, min(25, float(fps)))
    interval = 1.0 / fps

    while True:
        # Adjustable quality and FPS for latency tuning
        frame_bytes = stream.get_jpeg_frame(quality=quality)
        
        if frame_bytes:
            # Add cache control headers to prevent browser caching
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Cache-Control: no-cache, no-store, must-revalidate\r\n'
                   b'Pragma: no-cache\r\n'
                   b'Expires: 0\r\n'
                   b'\r\n' + frame_bytes + b'\r\n')
            
            frame_count += 1
            # Delay based on target FPS
            time.sleep(interval)
        else:
            # No frame available - wait longer
            time.sleep(0.2)
            
            # Check if stream is dead (no frames for 10 seconds)
            if time.time() - last_frame_time > 10:
                break


@farm_access_required
def camera_feed(request, camera_id):
    """
    Stream live video feed from a camera using MJPEG
    
    Args:
        camera_id: ID of the camera to stream
        
    Returns:
        StreamingHttpResponse: MJPEG stream with no-cache headers
    """
    # Verify camera exists and is active
    get_object_or_404(IPCamera, id=camera_id, is_active=True)
    
    try:
        quality = int(request.GET.get('quality', 85))
    except (TypeError, ValueError):
        quality = 85

    try:
        fps = float(request.GET.get('fps', 20))
    except (TypeError, ValueError):
        fps = 20

    response = StreamingHttpResponse(
        generate_mjpeg_stream(camera_id, quality=quality, fps=fps),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )
    
    # Disable caching for real-time streaming
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    
    return response


@farm_owner_required
@require_http_methods(["POST"])
def camera_connect(request):
    """
    Connect to a camera and start streaming
    
    Expects JSON body with:
        - position: Camera position name (north, south, etc.)
        - ip_address: Camera IP address
        - camera_type: Camera type (wifi, rtsp, http)
        - username: Camera username (optional)
        - password: Camera password (optional)
    
    Returns:
        JsonResponse: Status of the operation
    """
    import json
    data = json.loads(request.body)
    
    position = data.get('position')
    ip_address = data.get('ip_address')
    camera_type = data.get('camera_type', 'wifi')
    username = data.get('username', '')
    password = data.get('password', '')
    
    if not position or not ip_address:
        return JsonResponse({
            'success': False,
            'message': 'Missing required fields'
        }, status=400)
    
    # Determine port and stream paths based on camera type
    if camera_type == 'rtsp':
        port = 554
        # Build RTSP URL with credentials
        auth_part = f"{username}:{password}@" if username and password else ""
        # Common RTSP stream paths - try /stream first, camera will use get_stream_url() method
        rtsp_url = f"rtsp://{auth_part}{ip_address}:{port}/stream"
        http_url = ""
        stream_path = "/stream"
    else:  # wifi or http
        port = 80
        # Build HTTP URL with credentials
        auth_part = f"{username}:{password}@" if username and password else ""
        # Common HTTP/MJPEG stream paths
        http_url = f"http://{auth_part}{ip_address}:{port}/video"
        rtsp_url = ""
        stream_path = "/video"
    
    # Try to find existing camera by position or create new one
    camera_name = f"{position.title()} Camera"
    camera, created = IPCamera.objects.get_or_create(
        location=position,
        defaults={
            'camera_id': f'CAM_{position.upper()}',
            'name': camera_name,
            'ip_address': ip_address,
            'camera_type': camera_type,
            'port': port,
            'username': username,
            'password': password,
            'rtsp_url': rtsp_url,
            'http_url': http_url,
            'stream_path': stream_path,
            'is_active': True
        }
    )
    
    # Update camera settings if it already exists
    if not created:
        camera.ip_address = ip_address
        camera.camera_type = camera_type
        camera.port = port
        camera.username = username
        camera.password = password
        camera.rtsp_url = rtsp_url
        camera.http_url = http_url
        camera.stream_path = stream_path
        camera.is_active = True
        camera.save()
    
    # Start the stream
    stream = camera_manager.get_stream(camera.id)
    
    if stream:
        return JsonResponse({
            'success': True,
            'message': f'Camera {camera.name} connected successfully',
            'stream_url': f'/iot/camera/feed/{camera.id}/',
            'camera_id': camera.id
        })
    else:
        return JsonResponse({
            'success': False,
            'message': 'Failed to connect to camera. Check credentials and IP address.'
        }, status=500)


@farm_owner_required
@require_http_methods(["POST"])
def start_camera(request, camera_id):
    """
    Start streaming from a specific camera
    
    Args:
        camera_id: ID of the camera to start
        
    Returns:
        JsonResponse: Status of the operation
    """
    camera = get_object_or_404(IPCamera, id=camera_id)
    
    if not camera.is_active:
        return JsonResponse({
            'success': False,
            'message': 'Camera is not active'
        }, status=400)
    
    stream = camera_manager.get_stream(camera_id)
    
    if stream:
        return JsonResponse({
            'success': True,
            'message': f'Camera {camera.name} started successfully',
            'stream_url': f'/iot/camera/feed/{camera_id}/'
        })
    else:
        return JsonResponse({
            'success': False,
            'message': 'Failed to start camera stream'
        }, status=500)


@farm_owner_required
@require_http_methods(["POST"])
def stop_camera(request, camera_id):
    """
    Stop streaming from a specific camera
    
    Args:
        camera_id: ID of the camera to stop
        
    Returns:
        JsonResponse: Status of the operation
    """
    camera = get_object_or_404(IPCamera, id=camera_id)
    
    success = camera_manager.stop_stream(camera_id)
    
    if success:
        camera.mark_offline()
        return JsonResponse({
            'success': True,
            'message': f'Camera {camera.name} stopped successfully'
        })
    else:
        return JsonResponse({
            'success': False,
            'message': 'Camera stream was not running'
        }, status=400)


@farm_access_required
def camera_status(request, camera_id):
    """
    Get the current status of a camera
    
    Args:
        camera_id: ID of the camera
        
    Returns:
        JsonResponse: Camera status information
    """
    camera = get_object_or_404(IPCamera, id=camera_id)
    
    return JsonResponse({
        'id': camera.id,
        'name': camera.name,
        'ip_address': camera.ip_address,
        'is_active': camera.is_active,
        'status': camera.status,
        'last_connected': camera.last_connected.isoformat() if camera.last_connected else None,
        'camera_type': camera.camera_type,
        'location': camera.location
    })


@farm_access_required
def all_cameras_status(request):
    """
    Get status of all cameras
    
    Returns:
        JsonResponse: List of all cameras with their status
    """
    cameras = IPCamera.objects.all()
    
    cameras_data = []
    for camera in cameras:
        cameras_data.append({
            'id': camera.id,
            'name': camera.name,
            'ip_address': camera.ip_address,
            'is_active': camera.is_active,
            'status': camera.status,
            'location': camera.location,
            'last_connected': camera.last_connected.isoformat() if camera.last_connected else None,
        })
    
    return JsonResponse({
        'cameras': cameras_data,
        'total_cameras': len(cameras_data),
        'active_cameras': sum(1 for c in cameras_data if c['status'] == 'active'),
    })


@farm_access_required
def camera_snapshot(request, camera_id):
    """
    Capture and return a single snapshot from the camera
    
    Args:
        camera_id: ID of the camera
        
    Returns:
        HttpResponse: JPEG image
    """
    get_object_or_404(IPCamera, id=camera_id, is_active=True)
    stream = camera_manager.get_stream(camera_id)
    
    if stream:
        frame_bytes = stream.get_jpeg_frame(quality=95)  # Maximum quality for snapshots
        if frame_bytes:
            return HttpResponse(frame_bytes, content_type='image/jpeg')
    
    # Return placeholder
    return HttpResponse(status=204)


# ============ Actuator Control ViewSets ============

class ActuatorStateViewSet(viewsets.ModelViewSet):
    """ViewSet for controlling actuators (doors, lights)"""
    queryset = ActuatorState.objects.select_related('device').all()
    serializer_class = ActuatorStateSerializer
    permission_classes = [FarmRolePermission]
    
    def get_permissions(self):
        """Keep legacy ESP32 actions separate; enforce farm RBAC everywhere else."""
        if self.action in ['esp32_commands', 'esp32_sync_state']:
            return [HasLegacyDeviceKey()]
        return super().get_permissions()
    
    @action(detail=False, methods=['get'])
    def esp32_status(self, request):
        """
        Get actuator states for a specific ESP32 device
        Query params: device_id (integer)
        Returns: List of actuators for that device
        """
        device_id = request.query_params.get('device_id')
        
        if not device_id:
            return Response(
                {'error': 'device_id parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get actuators for devices owned by this ESP32
        actuators = ActuatorState.objects.filter(
            device__id=device_id
        ).select_related('device')
        
        serializer = self.get_serializer(actuators, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def control(self, request, pk=None):
        """
        Manually control actuator state.

        POST data: {"state": "on|off|open|closed", "triggered_by": "username"}

        Honesty note: the ESP32 firmware polls `esp32_commands` (~every 5s) and
        does NOT acknowledge that it physically executed a command. So we do not
        pretend the action succeeded. We record and report:
          - 'sent'   when the device is online (recent sensor activity) and will
                     pick the command up on its next poll, or
          - 'queued' when the device is offline and will only apply it later.
        The desired `current_state` is still written so the device contract
        (esp32_commands / current_state) is preserved exactly.
        """
        actuator = self.get_object()
        new_state = request.data.get('state')
        # Actor identity is authoritative server-side; never accept an
        # impersonable username from the browser.
        triggered_by = request.user.get_username()

        if new_state not in ['on', 'off', 'open', 'closed']:
            return Response(
                {'error': 'Invalid state. Use: on, off, open, or closed'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Determine action for logging
        action_map = {
            'on': 'turn_on',
            'off': 'turn_off',
            'open': 'open',
            'closed': 'close'
        }

        # Store previous state before updating
        previous_state = actuator.current_state

        # Is the controller currently reachable? (derived from recent sensor
        # activity — the ESP32 has no heartbeat field.)
        online = is_device_online(actuator.device)

        try:
            # Write the desired state for the device to pick up on its next poll.
            actuator.current_state = new_state
            actuator.mode = 'manual'  # Switch to manual mode
            actuator.last_triggered_by = triggered_by
            actuator.save()

            # Honest outcome: sent (online) vs queued (offline). Never a fake
            # 'success', because the hardware does not confirm execution.
            result = 'sent' if online else 'queued'
            ActuationLog.objects.create(
                device=actuator.device,
                action=action_map.get(new_state, 'turn_on'),
                source='manual',
                triggered_by=triggered_by,
                result=result,
                metadata={
                    'previous_state': previous_state,
                    'new_state': new_state,
                    'device_online': online,
                    'applies_via': 'device_poll',
                }
            )
        except Exception as e:
            logger.exception("Actuator control failed for %s", actuator)
            try:
                ActuationLog.objects.create(
                    device=actuator.device,
                    action=action_map.get(new_state, 'turn_on'),
                    source='manual',
                    triggered_by=triggered_by,
                    result='failed',
                    error_message=str(e),
                    metadata={'previous_state': previous_state,
                              'new_state': new_state},
                )
            except Exception:
                pass
            return Response(
                {'error': 'Failed to update actuator state'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if online:
            message = (f'Command sent to {actuator.device.name}. It will apply '
                       f'on the device\'s next check (~5s).')
        else:
            message = (f'{actuator.device.name} is offline. Command queued — it '
                       f'will apply when the device reconnects.')

        return Response({
            'message': message,
            'current_state': new_state,   # desired state
            'mode': 'manual',
            'result': result,
            'device_online': online,
            'applies_via': 'device_poll',
            # The current hardware does not report back that it executed the
            # command; the UI should present this as a request, not confirmation.
            'confirmation': 'not_reported_by_hardware',
        })

    
    @action(detail=False, methods=['get'])
    def esp32_commands(self, request):
        """
        ESP32 polls this endpoint to get actuator commands
        Query params: device_id (e.g., kamotech_esp32_001)
        Returns: Current state of all actuators for this device
        """
        device_id = request.query_params.get('device_id')
        
        if not device_id:
            return Response(
                {'error': 'device_id parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response(
                {'error': 'Device not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get all actuators for this device
        actuators = ActuatorState.objects.filter(device=device)
        
        commands = []
        for actuator in actuators:
            commands.append({
                'type': actuator.actuator_type,  # 'door' or 'light'
                'state': actuator.current_state,  # 'on', 'off', 'open', 'closed'
                'mode': actuator.mode,  # 'manual' or 'auto'
                'last_changed': actuator.last_changed_at.isoformat()
            })
        
        return Response({
            'device_id': device_id,
            'device_name': device.name,
            'commands': commands,
            'timestamp': timezone.now().isoformat()
        })
    
    @action(detail=False, methods=['post'])
    def esp32_sync_state(self, request):
        """
        ESP32 sends physical button state changes here to sync with Django
        POST data: {
            'device_id': 'kamotech_esp32_001',
            'actuator_type': 'door' or 'light',
            'state': 'on'/'off'/'open'/'closed',
            'triggered_by': 'physical_button' (optional)
        }
        """
        device_id = request.data.get('device_id')
        actuator_type = request.data.get('actuator_type')
        new_state = request.data.get('state')
        triggered_by = request.data.get('triggered_by', 'ESP32 Device')
        
        if not all([device_id, actuator_type, new_state]):
            return Response(
                {'error': 'device_id, actuator_type, and state required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            device = Device.objects.get(device_id=device_id)
        except Device.DoesNotExist:
            return Response(
                {'error': 'Device not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Store previous state
        current_actuator = ActuatorState.objects.filter(
            device=device,
            actuator_type=actuator_type
        ).first()
        previous_state = current_actuator.current_state if current_actuator else 'unknown'
        
        # Get or create the actuator state
        actuator_state, created = ActuatorState.objects.get_or_create(
            device=device,
            actuator_type=actuator_type,
            defaults={'current_state': new_state}
        )
        
        if not created:
            actuator_state.current_state = new_state
            actuator_state.last_changed_at = timezone.now()
            actuator_state.last_triggered_by = triggered_by
            actuator_state.save()
        
        # Map state to action for logging
        action_map = {
            'on': 'turn_on',
            'off': 'turn_off',
            'open': 'open',
            'closed': 'close'
        }
        
        # Create actuation log entry
        ActuationLog.objects.create(
            device=device,
            action=action_map.get(new_state, 'turn_on'),
            # Device-originated (physical button or ESP32 sync). triggered_by
            # keeps the finer distinction ('physical_button' vs 'ESP32 Device').
            source='device',
            triggered_by=triggered_by,
            result='success',
            metadata={
                'actuator_type': actuator_type,
                'previous_state': previous_state,
                'new_state': new_state,
                'device_id': device_id
            }
        )
        
        return Response({
            'success': True,
            'device_id': device_id,
            'actuator_type': actuator_type,
            'state': new_state,
            'previous_state': previous_state,
            'synced_at': timezone.now().isoformat(),
            'logged': True
        })
    
    @action(detail=True, methods=['post'])
    def toggle_mode(self, request, pk=None):
        """
        Toggle between manual and automatic mode
        
        POST data: {"mode": "manual|auto"}
        """
        actuator = self.get_object()
        new_mode = request.data.get('mode')
        
        if new_mode not in ['manual', 'auto']:
            return Response(
                {'error': 'Invalid mode. Use: manual or auto'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        actuator.mode = new_mode
        actuator.save()
        
        return Response({
            'message': f'{actuator.device.name} switched to {new_mode} mode',
            'mode': new_mode
        })


class AutomationRuleViewSet(viewsets.ModelViewSet):
    """ViewSet for automation rules"""
    queryset = AutomationRule.objects.select_related('actuator').all()
    serializer_class = AutomationRuleSerializer
    permission_classes = [FarmRolePermission]
    
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Toggle rule active/inactive"""
        rule = self.get_object()
        rule.is_active = not rule.is_active
        rule.save()
        
        return Response({
            'message': f'Rule "{rule.name}" {"activated" if rule.is_active else "deactivated"}',
            'is_active': rule.is_active
        })
    
    @action(detail=False, methods=['get'])
    def by_actuator(self, request):
        """Get rules for a specific actuator"""
        actuator_id = request.query_params.get('actuator_id')
        if not actuator_id:
            return Response(
                {'error': 'actuator_id parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        rules = self.queryset.filter(actuator_id=actuator_id)
        serializer = self.get_serializer(rules, many=True)
        return Response(serializer.data)


class ActuationLogViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing actuation logs (read-only)"""
    queryset = ActuationLog.objects.select_related('device', 'rule').all()
    serializer_class = ActuationLogSerializer
    permission_classes = [FarmRolePermission]
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get actuation statistics"""
        hours = _bounded_hours(request)
        since = timezone.now() - timedelta(hours=hours)
        
        logs = self.queryset.filter(timestamp__gte=since)
        
        counts = logs.aggregate(
            total_actions=Count('id'),
            manual_actions=Count('id', filter=Q(source='manual')),
            automated_actions=Count('id', filter=Q(source='rule')),
            successful_actions=Count('id', filter=Q(result='success')),
            failed_actions=Count('id', filter=Q(result='failed')),
        )
        return Response({
            **counts,
            'time_range_hours': hours
        })


# ============ Automation Control Dashboard ============

@farm_owner_required
def automation_control(request):
    """Dashboard for controlling automated door, lighting, and feeding systems"""
    from feeding.models import FeedSchedule
    
    # Get all actuators
    door_actuators = ActuatorState.objects.filter(
        actuator_type='door'
    ).select_related('device')
    
    light_actuators = ActuatorState.objects.filter(
        actuator_type='light'
    ).select_related('device')
    
    # Get feeder actuators
    feeder_actuators = ActuatorState.objects.filter(
        actuator_type='feeder'
    ).select_related('device')

    # Annotate each actuator with derived online status. There is no heartbeat
    # field on Device, so "online" means the actuator's device posted sensor
    # data within the recency window. Cache per device_id to avoid duplicate
    # queries (all actuators usually share one ESP32).
    _online_cache = {}

    def _annotate_online(qs):
        rows = list(qs)
        for a in rows:
            did = a.device_id
            if did not in _online_cache:
                _online_cache[did] = is_device_online(a.device)
            a.is_online = _online_cache[did]
        return rows

    door_actuators = _annotate_online(door_actuators)
    light_actuators = _annotate_online(light_actuators)
    feeder_actuators = _annotate_online(feeder_actuators)
    
    # Get time-based schedules from AutomationRule
    # Filter by device_type in criteria to avoid duplicates
    all_time_schedules = AutomationRule.objects.filter(rule_type='time_based')
    door_schedules = [s for s in all_time_schedules if s.criteria.get('device_type') == 'door']
    light_schedules = [s for s in all_time_schedules if s.criteria.get('device_type') == 'light']
    
    # Get feeding schedules
    feeder_schedules = FeedSchedule.objects.filter(
        feeder__device_type='feeder'
    ).order_by('schedule_time')
    
    # Format display for days
    for schedule in feeder_schedules:
        if schedule.days_of_week:
            days_map = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
            schedule.get_days_display = ', '.join([days_map[d] for d in schedule.days_of_week])
        else:
            schedule.get_days_display = 'Every day'
    
    # Get automation rules (sensor-based)
    automation_rules = AutomationRule.objects.filter(
        rule_type__in=['sensor_based', 'detection_based']
    )
    
    # Format condition display for rules
    for rule in automation_rules:
        conditions = []
        for key, value in rule.criteria.items():
            # Extract operator and value (e.g., '>30' -> '> 30')
            if value:
                operator = ''
                numeric_value = value
                for op in ['>=', '<=', '==', '>', '<']:
                    if value.startswith(op):
                        operator = op
                        numeric_value = value[len(op):].strip()
                        break
                
                # Format the condition nicely
                if key == 'temperature':
                    conditions.append(f"Temperature {operator} {numeric_value}°C")
                elif key == 'humidity':
                    conditions.append(f"Humidity {operator} {numeric_value}%")
                elif key == 'rain':
                    conditions.append("Rain is detected")
                elif key == 'distance':
                    conditions.append(f"Feeder distance {operator} {numeric_value} cm")
                elif key == 'goat_count':
                    conditions.append(f"Goat count {operator} {numeric_value}")
        
        rule.condition_display = ' AND '.join(conditions) if conditions else 'No conditions'
    
    # Format door and light schedules for display
    for schedule in door_schedules:
        if 'time' in schedule.criteria:
            schedule.time = schedule.criteria['time']
        if 'action' in schedule.criteria:
            schedule.action = schedule.criteria['action'].replace('_', ' ').title()
        if 'days_of_week' in schedule.criteria:
            days_map = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
            schedule.days = ', '.join([days_map[d] for d in schedule.criteria['days_of_week']])
    
    for schedule in light_schedules:
        if 'time' in schedule.criteria:
            schedule.time = schedule.criteria['time']
        if 'action' in schedule.criteria:
            schedule.action = schedule.criteria['action'].replace('_', ' ').title()
        if 'days_of_week' in schedule.criteria:
            days_map = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
            schedule.days = ', '.join([days_map[d] for d in schedule.criteria['days_of_week']])
    
    # Get all actuator devices for rule creation
    actuator_device_ids = list(ActuatorState.objects.values_list('device_id', flat=True))
    feeder_device_ids = list(Device.objects.filter(device_type='feeder').values_list('id', flat=True))
    all_actuators = Device.objects.filter(id__in=actuator_device_ids + feeder_device_ids)
    
    # Check if automation is enabled (master toggle)
    from django.core.cache import cache
    automation_enabled = cache.get('automation_enabled', True)  # Default to True
    
    # Get active automation rules
    active_rules = AutomationRule.objects.filter(
        is_active=True
    ).select_related('actuator').order_by('-priority')
    
    # Get recent actuation logs
    recent_logs = ActuationLog.objects.select_related(
        'device', 'rule'
    ).order_by('-timestamp')[:20]
    
    # Statistics for today
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_logs = ActuationLog.objects.filter(timestamp__gte=today_start)
    
    stats = {
        'total_actions_today': today_logs.count(),
        'manual_actions_today': today_logs.filter(source='manual').count(),
        'automated_actions_today': today_logs.filter(source='rule').count(),
        'door_operations': today_logs.filter(
            Q(action='open') | Q(action='close')
        ).count(),
        'light_operations': today_logs.filter(
            Q(action='turn_on') | Q(action='turn_off')
        ).count(),
        # Honest command outcomes (manual commands are 'sent'/'queued', not a
        # fake 'success', because the hardware does not acknowledge execution).
        'sent_today': today_logs.filter(result='sent').count(),
        'queued_today': today_logs.filter(result='queued').count(),
        'failed_today': today_logs.filter(result='failed').count(),
    }
    
    # Get latest sensor data from ESP32
    latest_temp = None
    latest_humidity = None
    latest_rain = False
    latest_distance = None
    
    latest_reading = SensorReading.objects.filter(
        device__device_id='kamotech_esp32_001'
    ).order_by('-timestamp').first()
    
    if latest_reading:
        latest_temp = latest_reading.temperature
        latest_humidity = latest_reading.humidity
        latest_rain = latest_reading.rain_detected
        latest_distance = latest_reading.feeder_level
    
    # FEEDING SYSTEM DATA
    feeders = []
    feed_schedules = []
    feeding_config = None
    recent_feed_logs = []
    feeding_stats = {
        'total_feedings_today': 0,
        'automated_feedings': 0,
        'scheduled_feedings': 0,
        'manual_feedings': 0,
    }
    
    if FeedLevel:
        feeders = FeedLevel.objects.select_related('feeder').all()
    
    if FeedSchedule:
        feed_schedules = FeedSchedule.objects.filter(
            is_active=True
        ).select_related('feeder').order_by('schedule_time')
    
    if AutomatedFeedingConfig:
        feeding_config = AutomatedFeedingConfig.get_config()
    
    # Import FeedLog if available
    try:
        from feeding.models import FeedLog
        recent_feed_logs = FeedLog.objects.select_related('feeder').order_by('-timestamp')[:10]
        
        today_feedings = FeedLog.objects.filter(timestamp__gte=today_start)
        feeding_stats['total_feedings_today'] = today_feedings.count()
        feeding_stats['automated_feedings'] = today_feedings.filter(feeding_mode='automated').count()
        feeding_stats['scheduled_feedings'] = today_feedings.filter(feeding_mode='scheduled').count()
        feeding_stats['manual_feedings'] = today_feedings.filter(feeding_mode='manual').count()
    except ImportError:
        pass
    
    context = {
        'door_actuators': door_actuators,
        'light_actuators': light_actuators,
        'feeder_actuators': feeder_actuators,
        'door_schedules': door_schedules,
        'light_schedules': light_schedules,
        'feeder_schedules': feeder_schedules,
        'automation_rules': automation_rules,
        'all_actuators': all_actuators,
        'automation_enabled': automation_enabled,
        # Derived controller status for the offline banner / control gating.
        'controller': controller_status(),
        'active_rules': active_rules,
        'recent_logs': recent_logs,
        'stats': stats,
        'latest_temp': latest_temp,
        'latest_humidity': latest_humidity,
        'latest_rain': latest_rain,
        'latest_distance': latest_distance,
        # Feeding data
        'feeders': feeders,
        'feed_schedules': feed_schedules,
        'feeding_config': feeding_config,
        'recent_feed_logs': recent_feed_logs,
        'feeding_stats': feeding_stats,
        'page_title': 'Automation Control - KaMoTech'
    }
    
    return render(request, 'iot/automation_control.html', context)


@staff_required
def camera_test(request):
    """Test page to verify camera feed is working"""
    camera = get_object_or_404(IPCamera, is_active=True)
    
    context = {
        'camera': camera,
    }
    
    return render(request, 'camera_test.html', context)


@farm_owner_required
def automation_schedule(request):
    """Automation schedules and rules management page"""
    from feeding.models import FeedSchedule
    
    # Get devices with actuator states
    door_actuator_states = ActuatorState.objects.filter(actuator_type='door').select_related('device')
    light_actuator_states = ActuatorState.objects.filter(actuator_type='light').select_related('device')
    
    # Get device IDs for door and light actuators
    door_device_ids = [state.device_id for state in door_actuator_states]
    light_device_ids = [state.device_id for state in light_actuator_states]
    
    # Get time-based schedules from AutomationRule
    door_schedules = AutomationRule.objects.filter(
        actuator_id__in=door_device_ids,
        rule_type='time_based'
    )
    light_schedules = AutomationRule.objects.filter(
        actuator_id__in=light_device_ids,
        rule_type='time_based'
    )
    
    # Get feeding schedules
    feeder_schedules = FeedSchedule.objects.filter(
        feeder__device_type='feeder'
    ).order_by('schedule_time')
    
    # Format display for days
    for schedule in feeder_schedules:
        if schedule.days_of_week:
            days_map = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
            schedule.get_days_display = ', '.join([days_map[d] for d in schedule.days_of_week])
        else:
            schedule.get_days_display = 'Every day'
    
    # Get automation rules (sensor-based)
    automation_rules = AutomationRule.objects.filter(
        rule_type__in=['sensor_based', 'detection_based']
    )
    
    # Format condition display for rules
    for rule in automation_rules:
        conditions = []
        for key, value in rule.criteria.items():
            # Extract operator and value (e.g., '>30' -> '> 30')
            if value:
                operator = ''
                numeric_value = value
                for op in ['>=', '<=', '==', '>', '<']:
                    if value.startswith(op):
                        operator = op
                        numeric_value = value[len(op):].strip()
                        break
                
                # Format the condition nicely
                if key == 'temperature':
                    conditions.append(f"Temperature {operator} {numeric_value}°C")
                elif key == 'humidity':
                    conditions.append(f"Humidity {operator} {numeric_value}%")
                elif key == 'rain':
                    conditions.append("Rain is detected")
                elif key == 'distance':
                    conditions.append(f"Feeder distance {operator} {numeric_value} cm")
                elif key == 'goat_count':
                    conditions.append(f"Goat count {operator} {numeric_value}")
        
        rule.condition_display = ' AND '.join(conditions) if conditions else 'No conditions'
    
    # Format door and light schedules for display
    for schedule in door_schedules:
        if 'time' in schedule.criteria:
            schedule.time = schedule.criteria['time']
        if 'action' in schedule.criteria:
            schedule.action = schedule.criteria['action'].replace('_', ' ').title()
        if 'days_of_week' in schedule.criteria:
            days_map = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
            schedule.days = ', '.join([days_map[d] for d in schedule.criteria['days_of_week']])
    
    for schedule in light_schedules:
        if 'time' in schedule.criteria:
            schedule.time = schedule.criteria['time']
        if 'action' in schedule.criteria:
            schedule.action = schedule.criteria['action'].replace('_', ' ').title()
        if 'days_of_week' in schedule.criteria:
            days_map = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
            schedule.days = ', '.join([days_map[d] for d in schedule.criteria['days_of_week']])
    
    # Get all actuator devices for rule creation (devices that have actuator states OR are feeders)
    actuator_device_ids = list(ActuatorState.objects.values_list('device_id', flat=True))
    feeder_device_ids = list(Device.objects.filter(device_type='feeder').values_list('id', flat=True))
    all_actuators = Device.objects.filter(id__in=actuator_device_ids + feeder_device_ids)
    
    # Check if automation is enabled (master toggle)
    from django.core.cache import cache
    automation_enabled = cache.get('automation_enabled', True)  # Default to True
    
    context = {
        'door_schedules': door_schedules,
        'light_schedules': light_schedules,
        'feeder_schedules': feeder_schedules,
        'automation_rules': automation_rules,
        'all_actuators': all_actuators,
        'automation_enabled': automation_enabled,
    }
    
    return render(request, 'iot/automation_schedule.html', context)


# ═══════════════════════════════════════════════════════════════════
# AUTOMATION API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@farm_owner_required
@require_http_methods(["POST"])
def api_create_schedule(request):
    """API to create time-based schedule for door/light/feeder"""
    try:
        # Parse request body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in request: {e}")
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON in request body'
            }, status=400)
        
        device_type = data.get('device_type')  # 'door', 'light', 'feeder'
        time = data.get('time')  # '08:00'
        action = data.get('action')  # 'open', 'close', 'on', 'off', 'dispense'
        days_of_week = data.get('days_of_week', [])  # [0,1,2,3,4,5,6]
        
        logger.info(f"Creating schedule: device={device_type}, time={time}, action={action}, days={days_of_week}")
        
        if not all([device_type, time, action]):
            return JsonResponse({
                'status': 'error',
                'message': 'Missing required fields'
            }, status=400)
        
        # Get the device based on device_type
        if device_type == 'feeder':
            device = Device.objects.filter(device_type='feeder').first()
            logger.info(f"Feeder device found: {device}")
        else:
            # For door/light, get device through ActuatorState
            actuator_state = ActuatorState.objects.filter(actuator_type=device_type).select_related('device').first()
            device = actuator_state.device if actuator_state else None
            logger.info(f"Actuator state for {device_type}: {actuator_state}, Device: {device}")
        
        if not device:
            logger.error(f"No {device_type} device found in database")
            return JsonResponse({
                'status': 'error',
                'message': f'No {device_type} device found. Please make sure the device is registered.'
            }, status=404)
        
        # For feeder, use FeedSchedule model
        if device_type == 'feeder':
            from feeding.models import FeedSchedule
            from datetime import datetime
            
            # Convert time string to datetime object
            time_obj = datetime.strptime(time, '%H:%M').time()
            
            schedule = FeedSchedule.objects.create(
                feeder=device,
                schedule_time=time_obj,
                amount_grams=100,  # Default amount
                is_active=True,
                days_of_week=days_of_week
            )
            
            return JsonResponse({
                'status': 'success',
                'message': 'Feeding schedule created',
                'schedule_id': schedule.id
            })
        else:
            # For door/light, use AutomationRule model
            # Map action to AutomationRule action format
            action_map = {
                'open': 'open_door',
                'close': 'close_door',
                'stop': 'close_door',
                'on': 'turn_on_light',
                'off': 'turn_off_light'
            }
            
            rule_action = action_map.get(action, action)
            
            # Create the automation rule
            rule = AutomationRule.objects.create(
                name=f"Schedule: {device.name} {action} at {time}",
                actuator=device,
                rule_type='time_based',
                action=rule_action,
                criteria={
                    'time': time,
                    'action': action,
                    'days_of_week': days_of_week,
                    'device_type': device_type  # Store which device type this is for
                },
                is_active=True,
                priority=0
            )
            
            return JsonResponse({
                'status': 'success',
                'message': 'Schedule created',
                'rule_id': rule.id
            })
        
    except Exception:
        logger.exception("Error creating schedule")
        return JsonResponse({
            'status': 'error',
            'message': 'Unable to create the schedule.'
        }, status=500)


@farm_owner_required
@require_http_methods(["POST"])
def api_toggle_schedule(request, schedule_id):
    """Toggle schedule active/inactive"""
    try:
        rule = AutomationRule.objects.get(id=schedule_id, rule_type='time_based')
        rule.is_active = not rule.is_active
        rule.save()
        
        return JsonResponse({
            'status': 'success',
            'is_active': rule.is_active
        })
    except AutomationRule.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Schedule not found'
        }, status=404)


@farm_owner_required
@require_http_methods(["DELETE"])
def api_delete_schedule(request, schedule_id):
    """Delete a schedule"""
    try:
        rule = AutomationRule.objects.get(id=schedule_id, rule_type='time_based')
        rule.delete()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Schedule deleted'
        })
    except AutomationRule.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Schedule not found'
        }, status=404)


@farm_owner_required
@require_http_methods(["POST"])
def api_create_rule(request):
    """API to create automation rule"""
    try:
        data = json.loads(request.body)
        name = data.get('name')
        actuator_id = data.get('actuator')
        action = data.get('action')
        criteria = data.get('criteria', {})
        priority = data.get('priority', 0)
        rule_type = data.get('rule_type', 'sensor_based')
        
        if not all([name, actuator_id, action]):
            return JsonResponse({
                'status': 'error',
                'message': 'Missing required fields'
            }, status=400)
        
        actuator = Device.objects.get(id=actuator_id)
        
        rule = AutomationRule.objects.create(
            name=name,
            actuator=actuator,
            rule_type=rule_type,
            action=action,
            criteria=criteria,
            is_active=True,
            priority=priority
        )
        
        return JsonResponse({
            'status': 'success',
            'message': 'Automation rule created',
            'rule_id': rule.id
        })
        
    except Device.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Device not found'
        }, status=404)
    except Exception:
        logger.exception("Error creating rule")
        return JsonResponse({
            'status': 'error',
            'message': 'Unable to create the automation rule.'
        }, status=500)


@farm_owner_required
@require_http_methods(["POST"])
def api_toggle_rule(request, rule_id):
    """Toggle rule active/inactive"""
    try:
        rule = AutomationRule.objects.get(id=rule_id)
        rule.is_active = not rule.is_active
        rule.save()
        
        return JsonResponse({
            'status': 'success',
            'is_active': rule.is_active
        })
    except AutomationRule.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Rule not found'
        }, status=404)


@farm_owner_required
@require_http_methods(["DELETE"])
def api_delete_rule(request, rule_id):
    """Delete an automation rule"""
    try:
        rule = AutomationRule.objects.get(id=rule_id)
        rule.delete()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Rule deleted'
        })
    except AutomationRule.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Rule not found'
        }, status=404)


@farm_owner_required
@require_http_methods(["POST"])
def api_toggle_automation(request):
    """Toggle master automation on/off"""
    try:
        data = json.loads(request.body)
        enabled = data.get('enabled', True)
        
        # Store in cache (or use a model if you prefer)
        from django.core.cache import cache
        cache.set('automation_enabled', enabled, timeout=None)  # Never expires
        
        return JsonResponse({
            'status': 'success',
            'message': f"Automation {'enabled' if enabled else 'disabled'}",
            'enabled': enabled
        })
    except Exception:
        logger.exception("Error toggling automation")
        return JsonResponse({
            'status': 'error',
            'message': 'Unable to update automation.'
        }, status=500)


@farm_owner_required
@require_http_methods(["POST"])
def api_update_schedule(request, schedule_id):
    """Update an existing schedule"""
    try:
        data = json.loads(request.body)
        
        rule = AutomationRule.objects.get(id=schedule_id, rule_type='time_based')
        
        # Update criteria
        if 'time' in data:
            rule.criteria['time'] = data['time']
        if 'action' in data:
            rule.criteria['action'] = data['action']
            # Update rule action too
            action_map = {
                'open': 'open_door',
                'close': 'close_door',
                'stop': 'close_door',
                'on': 'turn_on_light',
                'off': 'turn_off_light'
            }
            rule.action = action_map.get(data['action'], data['action'])
        if 'days_of_week' in data:
            rule.criteria['days_of_week'] = data['days_of_week']
        
        rule.save()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Schedule updated'
        })
    except AutomationRule.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Schedule not found'
        }, status=404)
    except Exception:
        logger.exception("Error updating schedule")
        return JsonResponse({
            'status': 'error',
            'message': 'Unable to update the schedule.'
        }, status=500)


@farm_owner_required
@require_http_methods(["POST"])
def api_update_rule(request, rule_id):
    """Update an existing automation rule"""
    try:
        data = json.loads(request.body)
        
        rule = AutomationRule.objects.get(id=rule_id)
        
        if 'name' in data:
            rule.name = data['name']
        if 'actuator' in data:
            rule.actuator = Device.objects.get(id=data['actuator'])
        if 'action' in data:
            rule.action = data['action']
        if 'criteria' in data:
            rule.criteria = data['criteria']
        if 'priority' in data:
            rule.priority = data['priority']
        
        rule.save()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Rule updated'
        })
    except AutomationRule.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Rule not found'
        }, status=404)
    except Exception:
        logger.exception("Error updating rule")
        return JsonResponse({
            'status': 'error',
            'message': 'Unable to update the automation rule.'
        }, status=500)
