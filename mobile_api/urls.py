from django.urls import path

from . import views
from .marketplace_views import (
    MarketplaceImageView, MarketplaceListingDetailView, MarketplaceListingListView,
    MarketplaceManagementDetailView, MarketplaceManagementImageActionView,
    MarketplaceManagementImageView, MarketplaceManagementView,
)
from .notification_views import (
    UnifiedNotificationActionView, UnifiedNotificationListView,
    UnifiedNotificationReadAllView, UnifiedNotificationSummaryView,
)
from .marketplace_transaction_views import (
    MarketplaceMessageImageView,
    MarketplaceSellerConversationDetailView, MarketplaceSellerConversationListView,
    MarketplaceSellerReservationActionView, MarketplaceSellerReservationListView,
)


app_name = "mobile_api"

urlpatterns = [
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("auth/realtime-ticket/", views.RealtimeTicketView.as_view(), name="realtime_ticket"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("notifications/", UnifiedNotificationListView.as_view(), name="notifications"),
    path("notifications/summary/", UnifiedNotificationSummaryView.as_view(), name="notification_summary"),
    path("notifications/read-all/", UnifiedNotificationReadAllView.as_view(), name="notifications_read_all"),
    path("notifications/<str:source_kind>/<int:pk>/", UnifiedNotificationActionView.as_view(), name="notification_action"),
    path("environment-history/", views.EnvironmentHistoryView.as_view(), name="environment_history"),
    path("report-summary/", views.ReportSummaryView.as_view(), name="report_summary"),
    path("goats/", views.GoatListView.as_view(), name="goats"),
    path("goats/options/", views.GoatOptionsView.as_view(), name="goat_options"),
    path("goats/<str:goat_id>/", views.GoatDetailView.as_view(), name="goat_detail"),
    path("goats/<str:goat_id>/images/", views.GoatPhotoManageView.as_view(), name="goat_photo_manage"),
    path("goats/<str:goat_id>/images/<int:image_pk>/", views.GoatPhotoActionView.as_view(), name="goat_photo_action"),
    path("goat-images/<int:pk>/", views.GoatImageView.as_view(), name="goat_image"),
    path("cameras/", views.CameraListView.as_view(), name="cameras"),
    path("cameras/<int:camera_id>/stream/", views.camera_stream, name="camera_stream"),
    path("live-detection/", views.LiveDetectionView.as_view(), name="live_detection"),
    path("tracking/", views.TrackingView.as_view(), name="tracking"),
    path("marketplace/listings/", MarketplaceListingListView.as_view(), name="marketplace_listings"),
    path("marketplace/listings/<int:pk>/", MarketplaceListingDetailView.as_view(), name="marketplace_listing_detail"),
    path("marketplace/images/<int:pk>/", MarketplaceImageView.as_view(), name="marketplace_image"),
    path("marketplace/manage/", MarketplaceManagementView.as_view(), name="marketplace_manage"),
    path("marketplace/manage/<int:pk>/", MarketplaceManagementDetailView.as_view(), name="marketplace_manage_detail"),
    path("marketplace/manage/<int:pk>/images/", MarketplaceManagementImageView.as_view(), name="marketplace_manage_images"),
    path("marketplace/manage/<int:pk>/images/<int:image_pk>/", MarketplaceManagementImageActionView.as_view(), name="marketplace_manage_image_action"),
    path("marketplace/seller/conversations/", MarketplaceSellerConversationListView.as_view(), name="marketplace_seller_conversations"),
    path("marketplace/seller/conversations/<int:pk>/", MarketplaceSellerConversationDetailView.as_view(), name="marketplace_seller_conversation_detail"),
    path("marketplace/seller/reservations/", MarketplaceSellerReservationListView.as_view(), name="marketplace_seller_reservations"),
    path("marketplace/seller/reservations/<int:pk>/", MarketplaceSellerReservationActionView.as_view(), name="marketplace_seller_reservation_action"),
    path("marketplace/messages/<int:pk>/image/", MarketplaceMessageImageView.as_view(), name="marketplace_message_image"),
]
