from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.http import FileResponse, Http404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from iot.goat_models import Goat, GoatImage
from marketplace.auth import FARM_OWNER_GROUP_NAME, can_manage_farm
from marketplace.forms import MultipleImageField
from marketplace.models import MarketplaceListing, SellerProfile
from marketplace.scopes import (
    can_manage_listing, manageable_goats, manageable_listing_q, manageable_listings,
)

from .marketplace_serializers import (
    MarketplaceListingDetailSerializer,
    MarketplaceListingSerializer, image_url,
)
from .permissions import HasActiveFarmAccess


def trusted_seller_q():
    return (
        Q(seller__is_staff=True)
        | Q(seller__is_superuser=True)
        | Q(seller__groups__name=FARM_OWNER_GROUP_NAME)
        | Q(seller__seller_profile__status=SellerProfile.APPROVED)
    )


def listing_queryset(active_only=True):
    queryset = (
        MarketplaceListing.objects.select_related(
            'goat', 'seller', 'seller__seller_profile'
        )
        .prefetch_related(
            Prefetch(
                'goat__images',
                queryset=GoatImage.objects.only(
                    'id', 'goat_id', 'image', 'angle', 'image_type',
                    'is_primary', 'uploaded_at'
                ).order_by('-uploaded_at'),
                to_attr='mobile_marketplace_images',
            )
        )
    )
    if active_only:
        queryset = queryset.filter(goat__status='active', goat__is_active=True)
    return queryset



class MarketplaceListingListView(generics.ListAPIView):
    permission_classes = [HasActiveFarmAccess]
    serializer_class = MarketplaceListingSerializer

    def get_queryset(self):
        listings = listing_queryset().filter(
                trusted_seller_q(),
                status__in=[MarketplaceListing.AVAILABLE, MarketplaceListing.RESERVED],
            ).distinct()
        query = self.request.query_params.get('search', '').strip()
        if query:
            listings = listings.filter(
                Q(goat__goat_id__icontains=query)
                | Q(goat__tag_number__icontains=query)
                | Q(goat__name__icontains=query)
                | Q(goat__breed__icontains=query)
                | Q(sales_description__icontains=query)
                | Q(seller__seller_profile__farm_name__icontains=query)
                | Q(seller__seller_profile__municipality__icontains=query)
                | Q(seller__seller_profile__province__icontains=query)
            )
        breed = self.request.query_params.get('breed', '').strip()
        gender = self.request.query_params.get('gender', '').strip()
        availability = self.request.query_params.get('availability', '').strip()
        if breed:
            listings = listings.filter(goat__breed=breed)
        if gender in {'male', 'female'}:
            listings = listings.filter(goat__gender=gender)
        if availability in {MarketplaceListing.AVAILABLE, MarketplaceListing.RESERVED}:
            listings = listings.filter(status=availability)
        for parameter, lookup in [('min_price', 'price__gte'), ('max_price', 'price__lte')]:
            value = self.request.query_params.get(parameter, '').strip()
            if value:
                try:
                    listings = listings.filter(**{lookup: Decimal(value)})
                except InvalidOperation:
                    pass
        ordering = {
            'newest': ('status', '-published_at', '-pk'),
            'price_low': ('status', 'price', '-pk'),
            'price_high': ('status', '-price', '-pk'),
            'weight_low': ('status', 'goat__weight_kg', '-pk'),
            'weight_high': ('status', '-goat__weight_kg', '-pk'),
            'updated': ('status', '-updated_at', '-pk'),
        }
        return listings.order_by(*ordering.get(
            self.request.query_params.get('sort', 'newest'), ordering['newest']
        ))


class MarketplaceListingDetailView(generics.RetrieveAPIView):
    permission_classes = [HasActiveFarmAccess]
    serializer_class = MarketplaceListingDetailSerializer

    def get_queryset(self):
        public = Q(
            trusted_seller_q(),
            status__in=[MarketplaceListing.AVAILABLE, MarketplaceListing.RESERVED],
            goat__status='active', goat__is_active=True,
        )
        manageable = manageable_listing_q(self.request.user)
        return listing_queryset(active_only=False).filter(
            public | manageable
        ).distinct()


class MarketplaceImageView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request, pk):
        image = GoatImage.objects.select_related(
            'goat__marketplace_listing__seller',
            'goat__marketplace_listing__seller__seller_profile',
        ).filter(pk=pk).first()
        if not image or not image.image:
            raise Http404
        try:
            listing = image.goat.marketplace_listing
        except MarketplaceListing.DoesNotExist:
            raise Http404
        public = (
            listing.status in {MarketplaceListing.AVAILABLE, MarketplaceListing.RESERVED}
            and MarketplaceListing.objects.filter(pk=listing.pk).filter(trusted_seller_q()).exists()
            and listing.goat.status == 'active'
            and listing.goat.is_active
        )
        if not public and not can_manage_listing(request.user, listing):
            raise Http404
        try:
            handle = image.image.open('rb')
        except (FileNotFoundError, ValueError):
            raise Http404
        response = FileResponse(handle)
        response['Cache-Control'] = 'private, max-age=300'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


def validation_message(exc):
    if hasattr(exc, 'message_dict'):
        return ' '.join(
            str(message)
            for messages in exc.message_dict.values()
            for message in messages
        )
    return ' '.join(exc.messages)


def eligible_goat_payload(request, goat):
    cover = GoatImage.preferred_from(getattr(goat, 'mobile_marketplace_images', []))
    return {
        'id': goat.pk,
        'goat_id': goat.goat_id,
        'name': goat.name,
        'breed_display': goat.get_breed_display(),
        'gender_display': goat.get_gender_display(),
        'age': goat.age_display,
        'weight_kg': goat.weight_kg,
        'cover_image_url': (
            request.build_absolute_uri(f'/api/mobile/goat-images/{cover.pk}/')
            if cover else None
        ),
    }


MOBILE_PHOTO_DESCRIPTION = 'Uploaded from GoHMoTech owner app'


def managed_listing(request, pk):
    if not can_manage_farm(request.user):
        return None
    return manageable_listings(
        request.user, listing_queryset(active_only=False)
    ).filter(pk=pk).first()


def managed_listing_response(request, listing_id):
    listing = manageable_listings(
        request.user, listing_queryset(active_only=False)
    ).get(pk=listing_id)
    return Response(MarketplaceListingDetailSerializer(
        listing, context={'request': request}
    ).data)


class MarketplaceManagementImageView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def post(self, request, pk):
        listing = managed_listing(request, pk)
        if not listing:
            return Response({'detail': 'Listing not found or not manageable.'}, status=404)
        if listing.status in {MarketplaceListing.RESERVED, MarketplaceListing.SOLD}:
            return Response({'detail': 'Photos cannot be changed for reserved or sold listings.'}, status=409)

        uploads = request.FILES.getlist('photos')
        if not uploads:
            return Response({'detail': 'Select at least one photo.'}, status=400)
        try:
            photos = MultipleImageField(required=False).clean(uploads)
        except ValidationError as exc:
            return Response({'detail': validation_message(exc)}, status=400)
        existing_count = listing.goat.images.count()
        if existing_count + len(photos) > 10:
            return Response({'detail': 'A goat can have no more than 10 photos.'}, status=400)

        with transaction.atomic():
            make_primary = not listing.goat.images.filter(is_primary=True).exists()
            for index, photo in enumerate(photos):
                GoatImage.objects.create(
                    goat=listing.goat,
                    image=photo,
                    image_type='identification',
                    description=MOBILE_PHOTO_DESCRIPTION,
                    is_training_data=False,
                    is_primary=make_primary and index == 0,
                )
        return managed_listing_response(request, listing.pk)


class MarketplaceManagementImageActionView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def post(self, request, pk, image_pk):
        listing = managed_listing(request, pk)
        if not listing:
            return Response({'detail': 'Listing not found or not manageable.'}, status=404)
        if listing.status in {MarketplaceListing.RESERVED, MarketplaceListing.SOLD}:
            return Response({'detail': 'Photos cannot be changed for reserved or sold listings.'}, status=409)
        image = GoatImage.objects.filter(pk=image_pk, goat=listing.goat).first()
        if not image:
            return Response({'detail': 'Photo not found for this listing.'}, status=404)

        action = str(request.data.get('action', '')).strip()
        if action == 'set_primary':
            with transaction.atomic():
                GoatImage.objects.filter(goat=listing.goat, is_primary=True).update(is_primary=False)
                image.is_primary = True
                image.save(update_fields=['is_primary'])
        elif action == 'delete':
            if image.description != MOBILE_PHOTO_DESCRIPTION:
                return Response({'detail': 'Only photos uploaded from the owner app can be deleted here.'}, status=403)
            if listing.status == MarketplaceListing.AVAILABLE and listing.goat.images.count() <= 1:
                return Response({'detail': 'Unpublish the listing before removing its final photo.'}, status=409)
            was_primary = image.is_primary
            image.image.delete(save=False)
            image.delete()
            if was_primary:
                replacement = listing.goat.images.order_by('-uploaded_at').first()
                if replacement:
                    replacement.is_primary = True
                    replacement.save(update_fields=['is_primary'])
        else:
            return Response({'detail': 'Use set_primary or delete.'}, status=400)
        return managed_listing_response(request, listing.pk)

class MarketplaceManagementView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def _allowed(self, request):
        return can_manage_farm(request.user)

    def get(self, request):
        if not self._allowed(request):
            return Response({'detail': 'Farm Owner or administrator access required.'}, status=403)
        listings = manageable_listings(
            request.user, listing_queryset(active_only=False)
        ).order_by('-updated_at', '-pk')
        goats = manageable_goats(
            request.user,
            Goat.all_objects.filter(
                status='active', is_active=True, marketplace_listing__isnull=True
            ).prefetch_related(
                Prefetch(
                    'images',
                    queryset=GoatImage.objects.only(
                        'id', 'goat_id', 'image', 'angle', 'image_type',
                        'is_primary', 'uploaded_at'
                    ).order_by('-uploaded_at'),
                    to_attr='mobile_marketplace_images',
                )
            ),
        ).order_by('goat_id')
        return Response({
            'listings': MarketplaceListingDetailSerializer(
                listings, many=True, context={'request': request}
            ).data,
            'eligible_goats': [eligible_goat_payload(request, goat) for goat in goats],
        })

    def post(self, request):
        if not self._allowed(request):
            return Response({'detail': 'Farm Owner or administrator access required.'}, status=403)
        try:
            price = Decimal(str(request.data.get('price', '')).strip())
        except (InvalidOperation, TypeError, ValueError):
            return Response({'detail': 'Enter a valid listing price.'}, status=400)
        description = str(request.data.get('sales_description', '')).strip()
        goat_id = request.data.get('goat_id')
        goat = manageable_goats(
            request.user,
            Goat.all_objects.filter(
                pk=goat_id, status='active', is_active=True,
                marketplace_listing__isnull=True,
            ),
        ).first()
        if not goat:
            return Response({'detail': 'Select an eligible unlisted goat.'}, status=400)
        if not description:
            return Response({'detail': 'Sales description is required.'}, status=400)
        listing = MarketplaceListing(
            goat=goat, seller=request.user, price=price,
            sales_description=description, status=MarketplaceListing.DRAFT,
        )
        try:
            listing.full_clean()
            listing.save()
        except ValidationError as exc:
            return Response({'detail': validation_message(exc)}, status=400)
        listing = manageable_listings(
            request.user, listing_queryset(active_only=False)
        ).get(pk=listing.pk)
        return Response(
            MarketplaceListingDetailSerializer(
                listing, context={'request': request}
            ).data,
            status=status.HTTP_201_CREATED,
        )


class MarketplaceManagementDetailView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get_listing(self, request, pk):
        if not can_manage_farm(request.user):
            return None
        return manageable_listings(
            request.user, listing_queryset(active_only=False)
        ).filter(pk=pk).first()

    def patch(self, request, pk):
        listing = self.get_listing(request, pk)
        if not listing:
            return Response({'detail': 'Listing not found or not manageable.'}, status=404)
        if listing.status in {MarketplaceListing.RESERVED, MarketplaceListing.SOLD}:
            return Response({'detail': 'Reserved or sold listings cannot be edited.'}, status=409)
        if 'price' in request.data:
            try:
                listing.price = Decimal(str(request.data['price']).strip())
            except (InvalidOperation, TypeError, ValueError):
                return Response({'detail': 'Enter a valid listing price.'}, status=400)
        if 'sales_description' in request.data:
            description = str(request.data['sales_description']).strip()
            if not description:
                return Response({'detail': 'Sales description is required.'}, status=400)
            listing.sales_description = description
        try:
            listing.full_clean()
            listing.save(update_fields=['price', 'sales_description', 'updated_at'])
        except ValidationError as exc:
            return Response({'detail': validation_message(exc)}, status=400)
        return Response(MarketplaceListingDetailSerializer(
            listing, context={'request': request}
        ).data)

    def post(self, request, pk):
        listing = self.get_listing(request, pk)
        if not listing:
            return Response({'detail': 'Listing not found or not manageable.'}, status=404)
        action = str(request.data.get('action', '')).strip()
        with transaction.atomic():
            listing = MarketplaceListing.objects.select_for_update().get(pk=listing.pk)
            if action == 'publish' and listing.status == MarketplaceListing.DRAFT:
                if not listing.goat.images.exists():
                    return Response({'detail': 'Add at least one goat photo before publishing.'}, status=400)
                listing.status = MarketplaceListing.AVAILABLE
                listing.published_at = timezone.now()
            elif action == 'unpublish' and listing.status == MarketplaceListing.AVAILABLE:
                listing.status = MarketplaceListing.DRAFT
            else:
                return Response({'detail': 'That publication change is not allowed.'}, status=409)
            try:
                listing.full_clean()
                listing.save(update_fields=['status', 'published_at', 'updated_at'])
            except ValidationError as exc:
                return Response({'detail': validation_message(exc)}, status=400)
        listing = self.get_listing(request, pk)
        return Response(MarketplaceListingDetailSerializer(
            listing, context={'request': request}
        ).data)