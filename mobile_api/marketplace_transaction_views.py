import os

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from marketplace.auth import can_manage_farm
from marketplace.forms import MessageForm
from marketplace.models import Conversation, MarketplaceNotification, Message, Reservation
from marketplace.notification_services import create_marketplace_notification
from marketplace.scopes import can_manage_listing, manageable_listing_q
from marketplace.services import (
    accept_reservation,
    cancel_reservation,
    complete_sale,
    confirm_pickup,
    expire_due_reservations,
    reject_reservation,
    suggest_pickup,
)

from .permissions import HasActiveFarmAccess


def error_text(exc):
    if hasattr(exc, 'message_dict'):
        return ' '.join(str(item) for values in exc.message_dict.values() for item in values)
    messages = getattr(exc, 'messages', None)
    return ' '.join(str(item) for item in messages) if messages else str(exc)


def require_farm_manager(request):
    if not can_manage_farm(request.user):
        return Response({'detail': 'Farm Owner or administrator access required.'}, status=403)
    return None


def seller_conversations(user):
    return (
        Conversation.objects.filter(manageable_listing_q(user, 'listing__'))
        .select_related('listing__goat', 'listing__seller', 'buyer')
        .annotate(
            unread_count=Count(
                'messages',
                filter=Q(messages__is_read=False) & ~Q(messages__sender=user),
            )
        )
        .order_by('-updated_at')
    )


def buyer_payload(user):
    return {
        'id': user.pk,
        'username': user.get_username(),
        'display_name': user.get_full_name() or user.get_username(),
    }


def reservation_actions(reservation):
    if reservation.status == Reservation.PENDING:
        return ['accept', 'reject']
    if reservation.status != Reservation.ACCEPTED:
        return []
    actions = ['cancel', 'suggest_pickup']
    if reservation.pickup_status == Reservation.PICKUP_REQUESTED:
        actions.append('confirm_pickup')
    if reservation.pickup_status == Reservation.PICKUP_CONFIRMED:
        actions.append('complete')
    return actions


def reservation_payload(reservation):
    return {
        'id': reservation.pk,
        'conversation_id': reservation.conversation_id,
        'listing_id': reservation.listing_id,
        'goat': {
            'goat_id': reservation.listing.goat.goat_id,
            'name': reservation.listing.goat.name,
            'breed_display': reservation.listing.goat.get_breed_display(),
        },
        'buyer': buyer_payload(reservation.buyer),
        'agreed_price': reservation.agreed_price,
        'status': reservation.status,
        'status_display': reservation.get_status_display(),
        'reserved_at': reservation.reserved_at,
        'accepted_at': reservation.accepted_at,
        'expires_at': reservation.expires_at,
        'rejection_reason': reservation.rejection_reason,
        'cancellation_reason': reservation.cancellation_reason,
        'pickup_datetime': reservation.pickup_datetime,
        'pickup_status': reservation.pickup_status,
        'pickup_status_display': reservation.get_pickup_status_display(),
        'pickup_notes': reservation.pickup_notes,
        'pickup_location': reservation.pickup_location,
        'completed_at': reservation.completed_at,
        'available_actions': reservation_actions(reservation),
    }


def message_payload(request, message):
    return {
        'id': message.pk,
        'body': message.body,
        'sender': buyer_payload(message.sender),
        'is_mine': message.sender_id == request.user.pk,
        'is_read': message.is_read,
        'created_at': message.created_at,
        'image_url': (
            request.build_absolute_uri(f'/api/mobile/marketplace/messages/{message.pk}/image/')
            if message.image_attachment else None
        ),
    }


def conversation_payload(conversation):
    latest = conversation.messages.select_related('sender').order_by('-created_at').first()
    active_reservation = conversation.reservations.filter(
        status__in=[Reservation.PENDING, Reservation.ACCEPTED]
    ).select_related('listing__goat', 'buyer').first()
    return {
        'id': conversation.pk,
        'listing_id': conversation.listing_id,
        'goat': {
            'goat_id': conversation.listing.goat.goat_id,
            'name': conversation.listing.goat.name,
            'breed_display': conversation.listing.goat.get_breed_display(),
        },
        'buyer': buyer_payload(conversation.buyer),
        'seller': buyer_payload(conversation.listing.seller),
        'status': conversation.status,
        'updated_at': conversation.updated_at,
        'unread_count': getattr(conversation, 'unread_count', 0),
        'latest_message': (
            {'body': latest.body or 'Image attached.', 'created_at': latest.created_at}
            if latest else None
        ),
        'active_reservation': reservation_payload(active_reservation) if active_reservation else None,
    }


def seller_reservations(user):
    return Reservation.objects.filter(
        manageable_listing_q(user, 'listing__')
    ).select_related('listing__goat', 'buyer', 'conversation').order_by('-reserved_at')


class MarketplaceSellerConversationListView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request):
        denied = require_farm_manager(request)
        if denied:
            return denied
        conversations = list(seller_conversations(request.user))
        return Response({
            'unread_count': sum(item.unread_count for item in conversations),
            'conversations': [conversation_payload(item) for item in conversations],
        })


class MarketplaceSellerConversationDetailView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get_conversation(self, request, pk):
        if not can_manage_farm(request.user):
            return None
        conversation = Conversation.objects.select_related(
            'listing__goat', 'listing__seller', 'buyer'
        ).filter(pk=pk).first()
        if not conversation or not can_manage_listing(request.user, conversation.listing):
            return None
        return conversation

    def get(self, request, pk):
        conversation = self.get_conversation(request, pk)
        if not conversation:
            return Response({'detail': 'Conversation not found or not manageable.'}, status=404)
        conversation.messages.exclude(sender=request.user).filter(is_read=False).update(is_read=True)
        expire_due_reservations()
        messages = conversation.messages.select_related('sender').order_by('created_at')
        reservations = conversation.reservations.select_related(
            'listing__goat', 'buyer'
        ).order_by('-reserved_at')
        payload = conversation_payload(conversation)
        payload['messages'] = [message_payload(request, item) for item in messages]
        payload['reservations'] = [reservation_payload(item) for item in reservations]
        payload['can_message'] = conversation.status == Conversation.OPEN
        return Response(payload)

    def post(self, request, pk):
        conversation = self.get_conversation(request, pk)
        if not conversation:
            return Response({'detail': 'Conversation not found or not manageable.'}, status=404)
        action = str(request.data.get('action', 'message')).strip()
        if action == 'message':
            if conversation.status != Conversation.OPEN:
                return Response({'detail': 'This conversation is closed.'}, status=409)
            form = MessageForm(request.data, request.FILES)
            if not form.is_valid():
                detail = ' '.join(
                    str(item)
                    for errors in form.errors.values()
                    for item in errors
                )
                return Response({'detail': detail or 'Enter a message or attach an image.'}, status=400)
            message = form.save(commit=False)
            message.conversation = conversation
            message.sender = request.user
            upload = form.cleaned_data.get('image_attachment')
            if upload:
                message.image_original_name = os.path.basename(upload.name)[:255]
                message.image_content_type = (upload.content_type or '')[:100]
                message.image_size = upload.size
            try:
                message.full_clean()
                with transaction.atomic():
                    message.save()
            except ValidationError as exc:
                return Response({'detail': error_text(exc)}, status=400)
            except (OSError, IOError):
                return Response({'detail': 'The image could not be uploaded. Please try again.'}, status=503)
            Conversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
            create_marketplace_notification(
                recipient=conversation.buyer,
                actor=request.user,
                notification_type=MarketplaceNotification.MESSAGE,
                title=f'New message about {conversation.listing.goat.goat_id}',
                message=message.body or 'Photo attachment',
                listing=conversation.listing,
                conversation=conversation,
                dedup_key=f'message:{message.pk}',
            )
            return Response(message_payload(request, message), status=status.HTTP_201_CREATED)
        if action == 'close' and conversation.status == Conversation.OPEN:
            conversation.status = Conversation.CLOSED
            conversation.closed_at = timezone.now()
            conversation.closed_by = request.user
        elif action == 'reopen' and conversation.status == Conversation.CLOSED:
            conversation.status = Conversation.OPEN
            conversation.closed_at = None
            conversation.closed_by = None
        else:
            return Response({'detail': 'That conversation action is not allowed.'}, status=409)
        conversation.save(update_fields=['status', 'closed_at', 'closed_by', 'updated_at'])
        return Response(conversation_payload(conversation))


class MarketplaceSellerReservationListView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request):
        denied = require_farm_manager(request)
        if denied:
            return denied
        expire_due_reservations()
        return Response({'reservations': [
            reservation_payload(item) for item in seller_reservations(request.user)
        ]})


class MarketplaceSellerReservationActionView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def post(self, request, pk):
        denied = require_farm_manager(request)
        if denied:
            return denied
        reservation = seller_reservations(request.user).filter(pk=pk).first()
        if not reservation:
            return Response({'detail': 'Reservation not found or not manageable.'}, status=404)
        action = str(request.data.get('action', '')).strip()
        try:
            if action == 'accept':
                accepted_until = request.data.get('expires_at')
                expires_at = parse_datetime(accepted_until) if accepted_until else None
                if accepted_until and expires_at is None:
                    raise ValidationError('Enter a valid reservation expiration.')
                accept_reservation(pk, request.user, expires_at, str(request.data.get('pickup_location', '')))
            elif action == 'reject':
                reject_reservation(pk, request.user, str(request.data.get('reason', '')))
            elif action == 'cancel':
                cancel_reservation(pk, request.user, str(request.data.get('reason', '')))
            elif action == 'suggest_pickup':
                value = parse_datetime(str(request.data.get('pickup_datetime', '')))
                if value is None:
                    raise ValidationError('Enter a valid pickup date and time.')
                suggest_pickup(
                    pk, request.user, value, str(request.data.get('pickup_notes', '')),
                    str(request.data.get('pickup_location', '')),
                )
            elif action == 'confirm_pickup':
                confirm_pickup(pk, request.user)
            elif action == 'complete':
                complete_sale(pk, request.user)
            else:
                return Response({'detail': 'That reservation action is not allowed.'}, status=400)
        except PermissionDenied as exc:
            return Response({'detail': str(exc)}, status=403)
        except ValidationError as exc:
            return Response({'detail': error_text(exc)}, status=409)
        reservation = seller_reservations(request.user).get(pk=pk)
        return Response(reservation_payload(reservation))


class MarketplaceMessageImageView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request, pk):
        message = Message.objects.select_related('conversation__listing').filter(pk=pk).first()
        if not message or not message.image_attachment:
            raise Http404
        if not message.conversation.user_is_participant(request.user):
            raise Http404
        try:
            handle = message.image_attachment.open('rb')
        except (FileNotFoundError, OSError, ValueError):
            raise Http404
        response = FileResponse(handle, content_type=message.image_content_type or 'application/octet-stream')
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
