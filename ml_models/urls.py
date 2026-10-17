from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# API Router
router = DefaultRouter()
router.register(r'models', views.MLModelViewSet, basename='mlmodel')
router.register(r'detections', views.DetectionViewSet, basename='detection')

app_name = 'ml_models'

urlpatterns = [
    # API endpoints
    path('api/', include(router.urls)),
    path('api/detect/', views.detect_goats_api, name='detect_api'),
    path('api/live-detection/', views.live_detection_control, name='live_detection_control'),
    path('api/user-presence/', views.user_presence_control, name='user_presence_control'),
    path('api/recognition/test/', views.test_recognition_api, name='test_recognition_api'),
    path('api/detect-stream/', views.detect_from_camera_stream, name='detect_stream'),
    
    # Web pages (Django templates)
    path('detection/', views.detection_feed_view, name='detection_feed'),
    path('active-users/', views.active_users_view, name='active_users'),
    path('detection/test/', views.test_detection_view, name='test_detection'),
    path('recognition/test/', views.test_detection_view, name='test_recognition'),
    path('detection/diagnostics/', views.diagnostics_view, name='diagnostics'),
    path('detection/history/', views.detection_history_view, name='detection_history'),
    path('models/', views.model_management_view, name='model_management'),
    path('models/<int:pk>/download/', views.download_model_file, name='download_model_file'),
]
