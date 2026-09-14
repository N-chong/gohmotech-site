from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.views.decorators.http import require_safe
from django.views.decorators.cache import never_cache

from marketplace.auth import has_farm_access


@require_safe
@never_cache
def media_file(request, name):
    from iot.models import GoatImage
    from marketplace.models import MarketplaceListing, SellerProfile
    from marketplace.views import _public_listing_queryset

    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise Http404

    user = request.user
    active_user = user.is_authenticated and user.is_active
    allowed = False
    if name.startswith('seller_documents/'):
        # Verification documents were previously linked using public media URLs.
        profile = SellerProfile.objects.filter(supporting_document=name).first()
        allowed = bool(profile and active_user and (user.is_staff or profile.user_id == user.pk))
    elif name.startswith('seller_profiles/'):
        profile = SellerProfile.objects.filter(profile_image=name).first()
        allowed = bool(profile and (
            profile.status == SellerProfile.APPROVED
            or (active_user and (user.is_staff or profile.user_id == user.pk))
        ))
    elif name.startswith('goat_images/'):
        photo = GoatImage.objects.select_related('goat').filter(image=name).first()
        if photo:
            allowed = _public_listing_queryset().filter(
                goat_id=photo.goat_id,
                status__in=[MarketplaceListing.AVAILABLE, MarketplaceListing.RESERVED],
            ).exists()
            allowed = allowed or bool(active_user and (
                has_farm_access(user) or photo.goat.owner_id == user.pk
            ))
    else:
        allowed = bool(active_user and has_farm_access(user))
    if not allowed:
        raise Http404
    response = FileResponse(target.open('rb'))
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response
