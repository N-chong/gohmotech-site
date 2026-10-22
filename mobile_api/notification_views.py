from django.utils import timezone
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from marketplace.models import MarketplaceNotification
from security.models import Notification as FarmNotification

from .permissions import HasActiveFarmAccess


MESSAGE_TYPES = {
    MarketplaceNotification.INQUIRY,
    MarketplaceNotification.MESSAGE,
}
TRANSACTION_TYPES = {
    MarketplaceNotification.RESERVATION,
    MarketplaceNotification.PICKUP,
    MarketplaceNotification.SALE,
}


def marketplace_target(notification):
    if notification.conversation_id:
        return f'/app/marketplace/conversations/{notification.conversation_id}'
    if notification.reservation_id:
        return '/app/marketplace/inbox'
    if notification.listing_id:
        return f'/app/marketplace/{notification.listing_id}'
    if notification.notification_type == MarketplaceNotification.SELLER_REVIEW:
        return '/app/marketplace'
    return '/app/alerts'


def farm_target(notification):
    if notification.notification_type == 'person_detection':
        return '/app/security'
    if notification.notification_type == 'missing_goat':
        return '/app/goats'
    if notification.notification_type == 'device_anomaly':
        return '/app/automation'
    return '/app/home'


def marketplace_payload(notification):
    if notification.notification_type in MESSAGE_TYPES:
        category = 'messages'
        severity = 'information'
    elif notification.notification_type in TRANSACTION_TYPES:
        category = 'transactions'
        severity = 'information'
    else:
        category = 'marketplace'
        severity = 'warning' if notification.notification_type == MarketplaceNotification.REPORT else 'information'
    return {
        'key': f'marketplace:{notification.pk}',
        'source_kind': 'marketplace',
        'source_id': notification.pk,
        'category': category,
        'notification_type': notification.notification_type,
        'type_display': notification.get_notification_type_display(),
        'title': notification.title,
        'message': notification.message,
        'source_label': 'Marketplace',
        'severity': severity,
        'is_read': notification.is_read,
        'is_resolved': False,
        'created_at': notification.created_at,
        'target': marketplace_target(notification),
    }


def farm_payload(notification):
    category = 'alerts'
    severity = (
        'critical' if notification.severity in {'critical', 'high'}
        else 'warning' if notification.severity in {'medium', 'low'}
        else 'information'
    )
    return {
        'key': f'farm:{notification.pk}',
        'source_kind': 'farm',
        'source_id': notification.pk,
        'category': category,
        'notification_type': notification.notification_type,
        'type_display': notification.get_notification_type_display(),
        'title': notification.title,
        'message': notification.description,
        'source_label': notification.source or 'Farm system',
        'severity': severity,
        'is_read': notification.is_read,
        'is_resolved': notification.is_resolved,
        'created_at': notification.created_at,
        'target': farm_target(notification),
    }


def notification_counts(user):
    marketplace = MarketplaceNotification.objects.filter(recipient=user)
    farm = FarmNotification.objects.all()
    farm_count = farm.count()
    marketplace_count = marketplace.count()
    message_count = marketplace.filter(notification_type__in=MESSAGE_TYPES).count()
    transaction_count = marketplace.filter(
        notification_type__in=TRANSACTION_TYPES
    ).count()
    farm_unread_count = farm.filter(is_read=False).count()
    marketplace_unread_count = marketplace.filter(is_read=False).count()
    return {
        'unread_count': farm_unread_count + marketplace_unread_count,
        'farm_unread_count': farm_unread_count,
        'marketplace_unread_count': marketplace_unread_count,
        'message_unread_count': marketplace.filter(
            is_read=False, notification_type__in=MESSAGE_TYPES
        ).count(),
        'facets': {
            'all': farm_count + marketplace_count,
            'alerts': farm_count,
            'messages': message_count,
            'transactions': transaction_count,
            'marketplace': marketplace_count,
        },
    }


class UnifiedNotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50


class UnifiedNotificationListView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request):
        selected = str(request.query_params.get('filter', 'all')).strip()
        items = []
        if selected in {'all', 'alerts'}:
            items.extend(
                farm_payload(item)
                for item in FarmNotification.objects.all().order_by('-created_at')
            )
        marketplace = MarketplaceNotification.objects.filter(
            recipient=request.user
        ).select_related(
            'listing', 'conversation', 'reservation'
        ).order_by('-created_at')
        if selected == 'messages':
            marketplace = marketplace.filter(notification_type__in=MESSAGE_TYPES)
        elif selected == 'transactions':
            marketplace = marketplace.filter(notification_type__in=TRANSACTION_TYPES)
        elif selected == 'alerts':
            marketplace = marketplace.none()
        if selected in {'all', 'marketplace', 'messages', 'transactions'}:
            items.extend(marketplace_payload(item) for item in marketplace)
        items.sort(key=lambda item: item['created_at'], reverse=True)
        paginator = UnifiedNotificationPagination()
        page = paginator.paginate_queryset(items, request, view=self)
        counts = notification_counts(request.user)
        return Response({
            'count': paginator.page.paginator.count,
            'next': paginator.get_next_link(),
            'previous': paginator.get_previous_link(),
            'results': page,
            **counts,
        })


class UnifiedNotificationSummaryView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request):
        return Response(notification_counts(request.user))


class UnifiedNotificationActionView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def post(self, request, source_kind, pk):
        if source_kind == 'marketplace':
            notification = MarketplaceNotification.objects.filter(
                pk=pk, recipient=request.user
            ).first()
        elif source_kind == 'farm':
            notification = FarmNotification.objects.filter(pk=pk).first()
        else:
            notification = None
        if not notification:
            return Response({'detail': 'Notification not found.'}, status=404)
        notification.mark_read()
        return Response({'key': f'{source_kind}:{pk}', 'is_read': True})


class UnifiedNotificationReadAllView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def post(self, request):
        now = timezone.now()
        marketplace_count = MarketplaceNotification.objects.filter(
            recipient=request.user, is_read=False
        ).update(is_read=True, read_at=now)
        farm_count = FarmNotification.objects.filter(is_read=False).update(
            is_read=True, read_at=now, updated_at=now
        )
        return Response({'marked_read': marketplace_count + farm_count})
