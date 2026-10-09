from django.urls import path
from . import views
from .onboarding import tutorial_state

app_name = 'dashboard'

urlpatterns = [
    path('system-logs/', views.system_logs_view, name='system_logs'),
    path('onboarding/state/', tutorial_state, name='tutorial_state'),
    path('service-worker.js', views.service_worker, name='service_worker'),
    path('', views.dashboard_home_view, name='home'),
    path('overview/', views.overview_view, name='overview'),
    path('map/', views.farm_map_view, name='farm_map'),
    path('features/', views.new_features_view, name='new_features'),
]
