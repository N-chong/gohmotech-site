from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DeviceViewSet, SensorDataViewSet, AlertViewSet, SensorReadingViewSet,
    ActuatorStateViewSet, AutomationRuleViewSet, ActuationLogViewSet,
    dashboard_modern, goats_list, goat_detail, add_goat, goat_photo_camera, devices_list, device_detail, monitoring_dashboard,
    automation_control, automation_schedule,
    # Camera views
    camera_feed, camera_connect, start_camera, stop_camera, camera_status, all_cameras_status, camera_snapshot,
    cameras_list, camera_detail, camera_test,
    # Automation APIs
    api_create_schedule, api_toggle_schedule, api_delete_schedule,
    api_create_rule, api_toggle_rule, api_delete_rule,
    api_toggle_automation, api_update_schedule, api_update_rule
)

# Phase 5: Enhanced Goat Management Views
from .goat_views import (
    goat_inventory, goat_comparison, goat_detail_enhanced, update_goat_status,
    missing_goat_alerts, resolve_alert, detection_history, upload_goat_image,
    delete_goat_image, scale_reading_ingest, goat_weight_live, save_goat_weight
)
from .owner_views import owner_actuator_control, owner_create_schedule, owner_dashboard
from .ble_api import (
    BLEObservationAPIView,
    BLEReceiverHeartbeatAPIView,
    BLETrackingSnapshotAPIView,
)
from .ble_views import ble_find_goat, ble_tracking_dashboard

router = DefaultRouter()
router.register(r'devices', DeviceViewSet)
router.register(r'sensor-data', SensorDataViewSet)
router.register(r'sensor-readings', SensorReadingViewSet)
router.register(r'alerts', AlertViewSet)
router.register(r'actuators', ActuatorStateViewSet)
router.register(r'automation-rules', AutomationRuleViewSet)
router.register(r'actuation-logs', ActuationLogViewSet)

urlpatterns = [
    path('owner/', owner_dashboard, name='owner_dashboard'),
    path('owner/actuators/<int:actuator_id>/control/', owner_actuator_control, name='owner_actuator_control'),
    path('owner/schedules/create/', owner_create_schedule, name='owner_create_schedule'),

    # Modern Dashboard (main landing page)
    path('', dashboard_modern, name='dashboard'),
    
    # Client-facing pages
    path('goats/', goats_list, name='goats_list'),  # Legacy view
    path('goats/add/', add_goat, name='add_goat'),
    path('goats/photo-camera/<slug:angle>/', goat_photo_camera, name='goat_photo_camera'),
    path('goats/<str:goat_id>/', goat_detail, name='goat_detail'),  # Legacy view
    
    # Phase 5: Enhanced Goat Management
    path('inventory/', goat_inventory, name='goat_inventory'),  # New main inventory page
    path('inventory/compare/', goat_comparison, name='goat_comparison'),
    path('inventory/<str:goat_id>/', goat_detail_enhanced, name='goat_detail_enhanced'),
    path('inventory/<str:goat_id>/upload-image/', upload_goat_image, name='upload_goat_image'),
    path('inventory/<str:goat_id>/update-status/', update_goat_status, name='update_goat_status'),
    path('inventory/<str:goat_id>/image/<int:image_id>/delete/', delete_goat_image, name='delete_goat_image'),
    path('inventory/<str:goat_id>/weight/live/', goat_weight_live, name='goat_weight_live'),
    path('inventory/<str:goat_id>/weight/save/', save_goat_weight, name='save_goat_weight'),
    path('alerts/', missing_goat_alerts, name='missing_goat_alerts'),
    path('alerts/<int:alert_id>/resolve/', resolve_alert, name='resolve_alert'),
    path('detections/', detection_history, name='detection_history'),
    path('tracking/', ble_tracking_dashboard, name='ble_tracking_dashboard'),
    path(
        'tracking/find/<str:goat_id>/',
        ble_find_goat,
        name='ble_find_goat',
    ),
    
    path('devices/', devices_list, name='devices_list'),
    path('devices/<str:device_id>/', device_detail, name='device_detail'),
    path('monitoring/', monitoring_dashboard, name='monitoring_dashboard'),
    
    # Automation Control
    path('automation/', automation_control, name='automation_control'),
    path('automation/schedules/', automation_schedule, name='automation_schedule'),
    
    # Automation API
    path('api/automation/toggle/', api_toggle_automation, name='api_toggle_automation'),
    path('api/schedules/create/', api_create_schedule, name='api_create_schedule'),
    path('api/schedules/<int:schedule_id>/toggle/', api_toggle_schedule, name='api_toggle_schedule'),
    path('api/schedules/<int:schedule_id>/update/', api_update_schedule, name='api_update_schedule'),
    path('api/schedules/<int:schedule_id>/delete/', api_delete_schedule, name='api_delete_schedule'),
    path('api/rules/create/', api_create_rule, name='api_create_rule'),
    path('api/rules/<int:rule_id>/toggle/', api_toggle_rule, name='api_toggle_rule'),
    path('api/rules/<int:rule_id>/update/', api_update_rule, name='api_update_rule'),
    path('api/rules/<int:rule_id>/delete/', api_delete_rule, name='api_delete_rule'),
    
    # Camera pages
    path('cameras/', cameras_list, name='cameras_list'),
    path('cameras/<int:camera_id>/', camera_detail, name='camera_detail'),
    path('camera/test/', camera_test, name='camera_test'),
    
    # Camera streaming endpoints
    path('camera/feed/<int:camera_id>/', camera_feed, name='camera_feed'),
    path('camera/snapshot/<int:camera_id>/', camera_snapshot, name='camera_snapshot'),
    
    # Camera control API
    path('api/camera/connect/', camera_connect, name='camera_connect'),
    path('api/camera/start/<int:camera_id>/', start_camera, name='camera_start'),
    path('api/camera/stop/<int:camera_id>/', stop_camera, name='camera_stop'),
    path('api/camera/status/<int:camera_id>/', camera_status, name='camera_status'),
    path('api/camera/status/', all_cameras_status, name='all_cameras_status'),
    
    # API endpoints
    path('api/ble/heartbeat/', BLEReceiverHeartbeatAPIView.as_view(), name='ble_receiver_heartbeat'),
    path('api/ble/observations/', BLEObservationAPIView.as_view(), name='ble_observation_ingest'),
    path('api/ble/tracking/', BLETrackingSnapshotAPIView.as_view(), name='ble_tracking_snapshot'),
    path('api/scale/readings/', scale_reading_ingest, name='scale_reading_ingest'),
    path('api/', include(router.urls)),
]
