from datetime import datetime, timedelta

from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from marketplace.decorators import farm_access_required, farm_owner_required

from feeding.models import FeedLevel, FeedLog, FeedSchedule
from iot.goat_models import GoatBehaviorLog, GoatDetectionHistory, GoatImage, IPCamera, MissingGoatAlert
from iot.goat_models import Goat
from iot.models import ActuationLog, ActuatorState, AutomationRule, SensorReading
from iot.weather_service import get_farm_weather
from iot.status_utils import is_device_online


def _get_owned_goats(user):
    """Single-owner mode: owner dashboard shows all goats."""
    return Goat.objects.all()


def _format_time_ago(dt):
    if not dt:
        return "Unknown"

    delta = timezone.now() - dt
    if delta < timedelta(minutes=1):
        return "just now"
    if delta < timedelta(hours=1):
        minutes = int(delta.total_seconds() // 60)
        return f"{minutes} min ago"
    if delta < timedelta(days=1):
        hours = int(delta.total_seconds() // 3600)
        return f"{hours} hr ago"
    days = delta.days
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def _get_report_window(request):
    """Build report date range from query params."""
    selected = request.GET.get("report_range", "weekly")
    now = timezone.now()
    start = None
    end = now

    start_date_raw = request.GET.get("start_date")
    end_date_raw = request.GET.get("end_date")

    if start_date_raw and end_date_raw:
        try:
            start_naive = datetime.strptime(start_date_raw, "%Y-%m-%d")
            end_naive = datetime.strptime(end_date_raw, "%Y-%m-%d")
            start = timezone.make_aware(start_naive.replace(hour=0, minute=0, second=0))
            end = timezone.make_aware(end_naive.replace(hour=23, minute=59, second=59))
        except ValueError:
            start = None

    if start is None:
        day_map = {
            "daily": 1,
            "weekly": 7,
            "monthly": 30,
        }
        start = now - timedelta(days=day_map.get(selected, 7))

    return selected, start, end


def _build_trend_points():
    """Generate compact 7-day chart points for mobile report charts."""
    points = []
    for i in range(6, -1, -1):
        day_start = (timezone.now() - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        alerts_count = MissingGoatAlert.objects.filter(triggered_at__gte=day_start, triggered_at__lt=day_end).count()
        feeds_count = FeedLog.objects.filter(timestamp__gte=day_start, timestamp__lt=day_end).count()

        points.append(
            {
                "label": day_start.strftime("%a"),
                "alerts": alerts_count,
                "feeds": feeds_count,
            }
        )

    return points


def _format_days(days):
    labels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    valid_days = [d for d in days if isinstance(d, int) and 0 <= d <= 6]
    if len(valid_days) == 7:
        return "Every day"
    return ", ".join(labels[d] for d in valid_days) if valid_days else "Not set"


@farm_owner_required
@require_POST
def owner_create_schedule(request):
    """Create a simple time-based automation schedule from owner mobile UI."""
    device_type = request.POST.get("device_type", "").strip().lower()
    schedule_time = request.POST.get("time", "").strip()
    action = request.POST.get("action", "").strip().lower()
    selected_days = request.POST.getlist("days")

    if not all([device_type, schedule_time, action]):
        messages.error(request, "Please select device, time, and action.")
        return redirect("owner_dashboard")

    try:
        day_values = sorted({int(d) for d in selected_days}) if selected_days else [0, 1, 2, 3, 4, 5, 6]
    except ValueError:
        messages.error(request, "Invalid day selection.")
        return redirect("owner_dashboard")

    if device_type == "feeder":
        feeder_state = ActuatorState.objects.filter(actuator_type="feeder").select_related("device").first()
        feeder_device = feeder_state.device if feeder_state else None
        if not feeder_device:
            messages.error(request, "No feeder device found for scheduling.")
            return redirect("owner_dashboard")

        try:
            parsed_time = datetime.strptime(schedule_time, "%H:%M").time()
        except ValueError:
            messages.error(request, "Invalid time format.")
            return redirect("owner_dashboard")

        amount = 100
        try:
            FeedSchedule.objects.create(
                feeder=feeder_device,
                schedule_time=parsed_time,
                amount_grams=amount,
                is_active=True,
                days_of_week=day_values,
            )
            messages.success(request, f"Feeder schedule created at {schedule_time}.")
        except Exception:
            messages.error(request, "Unable to create feeder schedule.")
        return redirect("owner_dashboard")

    actuator_state = ActuatorState.objects.filter(actuator_type=device_type).select_related("device").first()
    if not actuator_state:
        messages.error(request, f"No {device_type} actuator available for scheduling.")
        return redirect("owner_dashboard")

    action_map = {
        "open": "open_door",
        "close": "close_door",
        "on": "turn_on_light",
        "off": "turn_off_light",
    }
    mapped_action = action_map.get(action)
    if not mapped_action:
        messages.error(request, "Invalid action for selected device.")
        return redirect("owner_dashboard")

    try:
        AutomationRule.objects.create(
            name=f"Owner schedule: {actuator_state.device.name} {action} {schedule_time}",
            actuator=actuator_state.device,
            rule_type="time_based",
            action=mapped_action,
            criteria={
                "time": schedule_time,
                "action": action,
                "days_of_week": day_values,
                "device_type": device_type,
            },
            is_active=True,
            priority=0,
        )
        messages.success(request, f"{device_type.title()} schedule created at {schedule_time}.")
    except Exception:
        messages.error(request, "Unable to create automation schedule.")

    return redirect("owner_dashboard")


@farm_owner_required
@require_POST
def owner_actuator_control(request, actuator_id):
    """Owner-safe actuator control endpoint for mobile dashboard buttons."""
    actuator = get_object_or_404(ActuatorState, id=actuator_id)

    if actuator.actuator_type not in ["light", "fan", "feeder", "water", "door"]:
        return JsonResponse({"success": False, "message": "Actuator is not allowed for owner control."}, status=403)

    new_state = request.POST.get("state")
    if new_state not in ["on", "off", "open", "closed"]:
        return JsonResponse({"success": False, "message": "Invalid state."}, status=400)

    previous_state = actuator.current_state
    actuator.current_state = new_state
    actuator.mode = "manual"
    actuator.last_triggered_by = request.user.username
    actuator.save()

    action_map = {
        "on": "turn_on",
        "off": "turn_off",
        "open": "open",
        "closed": "close",
    }

    # Honest outcome: the ESP32 polls for commands and does not acknowledge
    # execution, so we report 'sent' (device online) or 'queued' (offline)
    # rather than a fake 'success'. Matches ActuatorStateViewSet.control.
    online = is_device_online(actuator.device)
    result = "sent" if online else "queued"

    ActuationLog.objects.create(
        device=actuator.device,
        action=action_map.get(new_state, "turn_on"),
        source="manual",
        triggered_by=request.user.username,
        result=result,
        metadata={
            "channel": "owner_mobile",
            "actuator_type": actuator.actuator_type,
            "previous_state": previous_state,
            "new_state": new_state,
            "device_online": online,
            "applies_via": "device_poll",
        },
    )

    if online:
        message = f"Command sent to {actuator.device.name}. Applies on its next check (~5s)."
    else:
        message = f"{actuator.device.name} is offline. Command queued until it reconnects."

    return JsonResponse(
        {
            "success": True,
            "message": message,
            "current_state": actuator.current_state,
            "actuator_type": actuator.actuator_type,
            "mode": actuator.mode,
            "result": result,
            "device_online": online,
            "applies_via": "device_poll",
            "confirmation": "not_reported_by_hardware",
            "last_changed": actuator.last_changed_at.isoformat(),
        }
    )


@farm_access_required
def owner_dashboard(request):
    """Role-aware farm operations dashboard using the shared application shell."""
    owned_goats = _get_owned_goats(request.user).order_by("goat_id")

    total_goats = owned_goats.count()
    active_goats = owned_goats.filter(is_active=True, status="active").count()
    missing_goats_count = owned_goats.filter(status="missing").count()
    goats_currently_detected = owned_goats.filter(
        last_seen__gte=timezone.now() - timedelta(minutes=5)
    ).count()
    healthy_goats = owned_goats.filter(health_status="healthy", status="active").count()
    goats_needing_attention = owned_goats.filter(
        Q(health_status__in=["monitoring", "sick", "quarantine"]) | Q(status="missing")
    ).count()

    goat_ids = owned_goats.values_list("id", flat=True)

    recent_alerts_qs = MissingGoatAlert.objects.filter(
        missing_goats__in=goat_ids
    ).distinct().order_by("-triggered_at")

    recent_alerts = list(recent_alerts_qs[:8])

    for alert in recent_alerts:
        alert.time_ago = _format_time_ago(alert.triggered_at)

    goats_with_images = []
    for goat in owned_goats:
        goat.latest_image = GoatImage.preferred_from(
            GoatImage.objects.filter(goat=goat)
        )
        latest_behavior = GoatBehaviorLog.objects.filter(goat=goat).order_by("-timestamp").first()
        goat.latest_behavior = latest_behavior
        goat.last_seen_ago = _format_time_ago(goat.last_seen) if goat.last_seen else "Never detected"
        goats_with_images.append(goat)

    latest_sensor = SensorReading.objects.order_by("-timestamp").first()

    activity_rows = []
    for goat in owned_goats[:12]:
        latest_behavior = GoatBehaviorLog.objects.filter(goat=goat).order_by("-timestamp").first()
        activity_rows.append(
            {
                "goat": goat,
                "behavior": latest_behavior.behavior_type if latest_behavior else "unknown",
                "last_seen": _format_time_ago(latest_behavior.timestamp) if latest_behavior else "No recent activity",
            }
        )

    latest_feed_log = FeedLog.objects.order_by("-timestamp").first()

    missing_alerts = list(
        recent_alerts_qs.filter(alert_type__in=["count_mismatch", "not_seen_recently"])[:5]
    )

    abnormal_health_alerts = []
    for goat in owned_goats.filter(health_status__in=["monitoring", "sick", "quarantine"])[:5]:
        abnormal_health_alerts.append(
            {
                "goat": goat,
                "message": f"{goat.goat_id} health status is {goat.get_health_status_display()}.",
                "time": _format_time_ago(goat.last_updated),
            }
        )

    unusual_movement_logs = GoatBehaviorLog.objects.filter(
        goat__in=goat_ids,
        behavior_type__in=["abnormal", "running", "inactive"],
    ).select_related("goat").order_by("-timestamp")[:8]

    recent_activity_logs = GoatBehaviorLog.objects.filter(goat__in=goat_ids).select_related("goat").order_by("-timestamp")[:8]
    health_history = owned_goats.order_by("-last_updated")[:8]

    location_history = GoatDetectionHistory.objects.filter(goat__in=goat_ids).select_related("goat", "camera").order_by("-timestamp")[:10]

    owner_camera = IPCamera.objects.filter(is_active=True).order_by("location").first()
    active_cameras = IPCamera.objects.filter(is_active=True)
    cameras_online = active_cameras.filter(status="active").count()
    cameras_total = active_cameras.count()

    owner_actuators = list(
        ActuatorState.objects.filter(actuator_type__in=["light", "fan", "feeder", "water", "door"])
        .select_related("device")
        .order_by("actuator_type", "device__name")
    )

    for actuator in owner_actuators:
        # Real online status derived from recent sensor activity (matches the
        # staff Automation page); the ESP32 has no heartbeat field, and
        # device.is_active is not a live signal.
        actuator.is_online = is_device_online(actuator.device)
        if actuator.actuator_type == "door":
            actuator.primary_action = "Open" if actuator.current_state != "open" else "Close"
            actuator.primary_state = "open" if actuator.current_state != "open" else "closed"
        elif actuator.actuator_type == "feeder":
            actuator.primary_action = "Activate"
            actuator.primary_state = "on"
        else:
            actuator.primary_action = "Turn ON" if actuator.current_state != "on" else "Turn OFF"
            actuator.primary_state = "on" if actuator.current_state != "on" else "off"

    all_owner_rules = AutomationRule.objects.filter(rule_type="time_based").order_by("-created_at")
    owner_automation_rules = []
    for rule in all_owner_rules:
        if rule.criteria.get("device_type") in ["door", "light"]:
            owner_automation_rules.append(rule)
        if len(owner_automation_rules) >= 8:
            break
    for rule in owner_automation_rules:
        days = rule.criteria.get("days_of_week", [])
        rule.schedule_time = rule.criteria.get("time", "--:--")
        rule.schedule_days = _format_days(days)
        rule.schedule_device_type = rule.criteria.get("device_type", "device")

    owner_feeder_schedules = list(FeedSchedule.objects.filter(is_active=True).select_related("feeder").order_by("-created_at")[:8])
    for sched in owner_feeder_schedules:
        sched.schedule_days = _format_days(sched.days_of_week or [])

    total_actuators = len(owner_actuators)
    online_actuators = sum(1 for actuator in owner_actuators if actuator.is_online)
    total_schedules = len(owner_automation_rules) + len(owner_feeder_schedules)
    camera_online = bool(owner_camera and owner_camera.is_active and owner_camera.status == "active")

    feed_levels = FeedLevel.objects.all()
    total_feed_grams = sum(level.current_level_grams for level in feed_levels)
    total_capacity_grams = sum(level.capacity_grams for level in feed_levels)
    if total_capacity_grams > 0:
        feed_level_percent = int(max(0, min(100, round((total_feed_grams / total_capacity_grams) * 100))))
    else:
        feed_level_percent = 0

    report_range, report_start, report_end = _get_report_window(request)

    report_alerts = MissingGoatAlert.objects.filter(triggered_at__gte=report_start, triggered_at__lte=report_end)
    report_feeds = FeedLog.objects.filter(timestamp__gte=report_start, timestamp__lte=report_end)
    report_sensors = SensorReading.objects.filter(timestamp__gte=report_start, timestamp__lte=report_end)
    report_behaviors = GoatBehaviorLog.objects.filter(timestamp__gte=report_start, timestamp__lte=report_end)

    daily_summary = {
        "alerts": MissingGoatAlert.objects.filter(triggered_at__gte=timezone.now() - timedelta(days=1)).count(),
        "feeds": FeedLog.objects.filter(timestamp__gte=timezone.now() - timedelta(days=1)).count(),
        "behaviors": GoatBehaviorLog.objects.filter(timestamp__gte=timezone.now() - timedelta(days=1)).count(),
    }
    weekly_summary = {
        "alerts": MissingGoatAlert.objects.filter(triggered_at__gte=timezone.now() - timedelta(days=7)).count(),
        "feeds": FeedLog.objects.filter(timestamp__gte=timezone.now() - timedelta(days=7)).count(),
        "behaviors": GoatBehaviorLog.objects.filter(timestamp__gte=timezone.now() - timedelta(days=7)).count(),
    }
    monthly_summary = {
        "alerts": MissingGoatAlert.objects.filter(triggered_at__gte=timezone.now() - timedelta(days=30)).count(),
        "feeds": FeedLog.objects.filter(timestamp__gte=timezone.now() - timedelta(days=30)).count(),
        "behaviors": GoatBehaviorLog.objects.filter(timestamp__gte=timezone.now() - timedelta(days=30)).count(),
    }

    health_report = {
        "healthy": Goat.objects.filter(health_status="healthy", status="active").count(),
        "monitoring": Goat.objects.filter(health_status="monitoring").count(),
        "sick": Goat.objects.filter(health_status="sick").count(),
        "missing": Goat.objects.filter(status="missing").count(),
    }

    feeding_report = {
        "manual": report_feeds.filter(feeding_mode="manual").count(),
        "scheduled": report_feeds.filter(feeding_mode="scheduled").count(),
        "automated": report_feeds.filter(feeding_mode="automated").count(),
        "total": report_feeds.count(),
    }

    avg_temp = None
    avg_humidity = None
    if report_sensors.exists():
        valid_temps = [s.temperature for s in report_sensors if s.temperature is not None]
        valid_humidities = [s.humidity for s in report_sensors if s.humidity is not None]
        if valid_temps:
            avg_temp = round(sum(valid_temps) / len(valid_temps), 1)
        if valid_humidities:
            avg_humidity = round(sum(valid_humidities) / len(valid_humidities), 1)

    environmental_report = {
        "avg_temperature": avg_temp,
        "avg_humidity": avg_humidity,
        "samples": report_sensors.count(),
    }

    trend_points = _build_trend_points()
    weather_info = get_farm_weather()

    context = {
        "total_goats": total_goats,
        "active_goats": active_goats,
        "missing_goats_count": missing_goats_count,
        "goats_currently_detected": goats_currently_detected,
        "healthy_goats": healthy_goats,
        "goats_needing_attention": goats_needing_attention,
        "recent_alerts": recent_alerts,
        "owned_goats": goats_with_images,
        "latest_sensor": latest_sensor,
        "activity_rows": activity_rows,
        "latest_feed_log": latest_feed_log,
        "missing_alerts": missing_alerts,
        "abnormal_health_alerts": abnormal_health_alerts,
        "unusual_movement_logs": unusual_movement_logs,
        "recent_activity_logs": recent_activity_logs,
        "health_history": health_history,
        "location_history": location_history,
        "owner_camera": owner_camera,
        "cameras_online": cameras_online,
        "cameras_total": cameras_total,
        "owner_actuators": owner_actuators,
        "owner_automation_rules": owner_automation_rules,
        "owner_feeder_schedules": owner_feeder_schedules,
        "camera_online": camera_online,
        "online_actuators": online_actuators,
        "total_actuators": total_actuators,
        "total_schedules": total_schedules,
        "feed_level_percent": feed_level_percent,
        "total_feed_grams": total_feed_grams,
        "total_capacity_grams": total_capacity_grams,
        "last_sync_time": timezone.now(),
        "report_range": report_range,
        "report_start": report_start,
        "report_end": report_end,
        "report_alerts_count": report_alerts.count(),
        "report_behaviors_count": report_behaviors.count(),
        "report_feeds_count": report_feeds.count(),
        "daily_summary": daily_summary,
        "weekly_summary": weekly_summary,
        "monthly_summary": monthly_summary,
        "health_report": health_report,
        "feeding_report": feeding_report,
        "environmental_report": environmental_report,
        "trend_points": trend_points,
        "weather_info": weather_info,
        "owner_name": request.user.get_full_name() or request.user.username,
    }

    return render(request, "iot/owner_dashboard.html", context)
