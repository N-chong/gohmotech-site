from rest_framework import serializers

from iot.goat_models import GoatImage
from marketplace.auth import can_manage_farm, seller_profile_for
from marketplace.models import MarketplaceListing
from marketplace.scopes import can_manage_listing


def image_url(request, image):
    if image is None or not image.image:
        return None
    path = f'/api/mobile/marketplace/images/{image.pk}/'
    return request.build_absolute_uri(path) if request else path


class MarketplaceListingSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    goat = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    cover_image_url = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()

    class Meta:
        model = MarketplaceListing
        fields = [
            'id', 'price', 'status', 'status_display', 'is_featured',
            'published_at', 'updated_at', 'goat', 'seller', 'cover_image_url',
            'can_manage',
        ]

    def get_goat(self, obj):
        goat = obj.goat
        return {
            'id': goat.pk,
            'goat_id': goat.goat_id,
            'name': goat.name,
            'tag_number': goat.tag_number,
            'breed': goat.breed,
            'breed_display': goat.get_breed_display(),
            'gender': goat.gender,
            'gender_display': goat.get_gender_display(),
            'age': goat.age_display,
            'weight_kg': goat.weight_kg,
            'health_status': goat.health_status,
            'health_status_display': goat.get_health_status_display(),
        }

    def get_seller(self, obj):
        profile = seller_profile_for(obj.seller)
        smart_farm = can_manage_farm(obj.seller)
        return {
            'id': profile.pk if profile else None,
            'farm_name': profile.farm_name if profile else (obj.seller.get_full_name() or obj.seller.get_username()),
            'location': profile.public_location if profile else '',
            'badge': 'GoHMoTech Smart Farm' if smart_farm else 'Approved Seller',
            'verified': smart_farm or bool(profile and profile.is_approved),
        }

    def get_cover_image_url(self, obj):
        photos = getattr(obj.goat, 'mobile_marketplace_images', [])
        return image_url(self.context.get('request'), GoatImage.preferred_from(photos))

    def get_can_manage(self, obj):
        request = self.context.get('request')
        return bool(request and can_manage_listing(request.user, obj))


class MarketplaceListingDetailSerializer(MarketplaceListingSerializer):
    sales_description = serializers.CharField(read_only=True)
    images = serializers.SerializerMethodField()
    livestock_details = serializers.SerializerMethodField()

    class Meta(MarketplaceListingSerializer.Meta):
        fields = MarketplaceListingSerializer.Meta.fields + [
            'sales_description', 'images', 'livestock_details',
        ]

    def get_images(self, obj):
        request = self.context.get('request')
        return [
            {
                'id': photo.pk,
                'image_url': image_url(request, photo),
                'angle': photo.angle,
                'angle_display': photo.get_angle_display() if photo.angle else '',
                'image_type': photo.image_type,
                'is_primary': photo.is_primary,
                'can_delete': photo.description == 'Uploaded from GoHMoTech owner app',
            }
            for photo in getattr(obj.goat, 'mobile_marketplace_images', [])
            if photo.image
        ]

    def get_livestock_details(self, obj):
        goat = obj.goat
        return {
            'date_of_birth': goat.date_of_birth,
            'color_markings': goat.color_markings,
            'health_notes': goat.health_notes,
            'vaccination_status': goat.vaccination_status,
            'vaccination_status_display': goat.get_vaccination_status_display(),
            'vaccine_name': goat.vaccine_name,
            'vaccination_date': goat.vaccination_date,
            'next_due_date': goat.next_due_date,
        }