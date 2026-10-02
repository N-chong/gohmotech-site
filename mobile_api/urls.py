from django.urls import path

from . import views


app_name = "mobile_api"

urlpatterns = [
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("auth/realtime-ticket/", views.RealtimeTicketView.as_view(), name="realtime_ticket"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("goats/", views.GoatListView.as_view(), name="goats"),
    path("goats/<str:goat_id>/", views.GoatDetailView.as_view(), name="goat_detail"),
    path("goat-images/<int:pk>/", views.GoatImageView.as_view(), name="goat_image"),
    path("cameras/", views.CameraListView.as_view(), name="cameras"),
    path("cameras/<int:camera_id>/stream/", views.camera_stream, name="camera_stream"),
    path("tracking/", views.TrackingView.as_view(), name="tracking"),
]
