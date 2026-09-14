from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.db.models import Count
from iot.models import Device
from ml_models.models import Detection
from feeding.models import FeedLog
from marketplace.auth import has_farm_access
from marketplace.decorators import farm_access_required


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


def dashboard_home_view(request):
    """Send public visitors and signed-in users to the right experience."""
    if not request.user.is_authenticated:
        return redirect('/marketplace/')
    if not has_farm_access(request.user):
        return redirect('/marketplace/')
    if request.user.is_staff or request.user.is_superuser:
        return redirect('/iot/')
    return redirect('/iot/owner/')


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
