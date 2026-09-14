from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('service-worker.js', views.service_worker, name='service_worker'),
    path('', views.dashboard_home_view, name='home'),
    path('overview/', views.overview_view, name='overview'),
    path('map/', views.farm_map_view, name='farm_map'),
    path('features/', views.new_features_view, name='new_features'),
]
