from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import datetime, time, timedelta
from iot.models import Device
from ml_models.models import Detection
from feeding.models import FeedLog
from marketplace.auth import default_page_name
from marketplace.decorators import farm_access_required, staff_required
from .models import SystemLog


@require_safe
@never_cache
def service_worker(request):
    """Serve the worker at the origin root so it can control the whole PWA."""
    worker = Path(settings.BASE_DIR) / "static" / "js" / "service-worker.js"
    if not worker.is_file():
        raise Http404
    response = FileResponse(worker.open("rb"), content_type="text/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    return response


@never_cache
def dashboard_home_view(request):
    """Send public visitors and signed-in users to the right experience."""
    return redirect(default_page_name(request.user))


def _safe_error_response(status, title, message):
    # Render without a RequestContext. Error pages must still work when a
    # database-backed context processor is the component that failed.
    html = get_template('error.html').render({
        'status_code': status,
        'error_title': title,
        'error_message': message,
    })
    return HttpResponse(html, status=status)


def bad_request_view(request, exception=None):
    return _safe_error_response(400, 'Request not accepted', 'Check the submitted information and try again.')


def permission_denied_view(request, exception=None):
    return _safe_error_response(403, 'Access denied', 'Your account does not have permission to open this resource.')


def not_found_view(request, exception=None):
    return _safe_error_response(404, 'Page not found', 'The requested page may have moved or may not be available to your account.')


def server_error_view(request):
    return _safe_error_response(500, 'GoHMoTech is temporarily unavailable', 'No data was changed. Please try again in a moment.')


@farm_access_required
def new_features_view(request):
    """New features guide page"""
    return render(request, 'dashboard/new_features.html', {
        'page_title': 'New Features Guide'
    })


@farm_access_required
def overview_view(request):
    """System overview page"""
    devices = Device.objects.filter(is_active=True)
    
    # Group devices by type
    devices_by_type = devices.values('device_type').annotate(count=Count('id'))
    
    # Recent activity
    recent_detections = Detection.objects.select_related('camera').order_by('-timestamp')[:10]
    recent_feeds = FeedLog.objects.select_related('feeder').order_by('-timestamp')[:10]
    
    context = {
        'devices': devices,
        'devices_by_type': devices_by_type,
        'recent_detections': recent_detections,
        'recent_feeds': recent_feeds,
        'page_title': 'System Overview'
    }
    
    return render(request, 'dashboard/overview.html', context)


@farm_access_required
def farm_map_view(request):
    """Farm map visualization page"""
    devices = Device.objects.filter(is_active=True)
    
    # Group devices by location
    devices_with_location = devices.exclude(location='')
    
    context = {
        'devices': devices_with_location,
        'page_title': 'Farm Map'
    }
    
    return render(request, 'dashboard/farm_map.html', context)


@staff_required
@never_cache
def system_logs_view(request):
    """Searchable, read-only system audit log for administrators."""
    logs = SystemLog.objects.select_related("actor")
    query = request.GET.get("q", "").strip()[:200]
    level = request.GET.get("level", "").strip()
    category = request.GET.get("category", "").strip()
    date_from = parse_date(request.GET.get("date_from", ""))
    date_to = parse_date(request.GET.get("date_to", ""))

    valid_levels = {choice[0] for choice in SystemLog.LEVEL_CHOICES}
    valid_categories = {choice[0] for choice in SystemLog.CATEGORY_CHOICES}
    if query:
        logs = logs.filter(
            Q(event__icontains=query)
            | Q(message__icontains=query)
            | Q(source__icontains=query)
            | Q(actor_label__icontains=query)
            | Q(path__icontains=query)
            | Q(ip_address__icontains=query)
        )
    if level in valid_levels:
        logs = logs.filter(level=level)
    else:
        level = ""
    if category in valid_categories:
        logs = logs.filter(category=category)
    else:
        category = ""
    if date_from:
        logs = logs.filter(created_at__gte=timezone.make_aware(datetime.combine(date_from, time.min)))
    if date_to:
        logs = logs.filter(created_at__lt=timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min)))

    paginator = Paginator(logs, 50)
    page = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    since = timezone.now() - timedelta(hours=24)
    recent = SystemLog.objects.filter(created_at__gte=since)

    return render(request, "dashboard/system_logs.html", {
        "page": page,
        "levels": SystemLog.LEVEL_CHOICES,
        "categories": SystemLog.CATEGORY_CHOICES,
        "selected_level": level,
        "selected_category": category,
        "query": query,
        "date_from": date_from,
        "date_to": date_to,
        "query_string": query_params.urlencode(),
        "total_count": SystemLog.objects.count(),
        "recent_count": recent.count(),
        "recent_warning_count": recent.filter(level=SystemLog.LEVEL_WARNING).count(),
        "recent_error_count": recent.filter(level__in=[SystemLog.LEVEL_ERROR, SystemLog.LEVEL_CRITICAL]).count(),
    })
