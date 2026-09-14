from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST

from iot.models import Goat, GoatImage

from .auth import (
    BUYER_GROUP_NAME, FARM_OPERATOR_GROUP_NAME, FARM_OWNER_GROUP_NAME,
    is_approved_seller, seller_profile_for,
)
from .decorators import approved_seller_required, seller_applicant_required, staff_required
from .forms import (
    CommunityGoatForm,
    ListingForm,
    MessageForm,
    MarketplaceReportForm,
    PickupRequestForm,
    ProfileCompletionForm,
    ReservationAcceptanceForm,
    SellerApplicationForm,
    SellerPickupSuggestionForm,
    SupportAdminUpdateForm,
    SupportReplyForm,
    SupportTicketForm,
)
from .models import (
    Conversation,
    MarketplaceActivity,
    MarketplaceNotification,
    MarketplaceListing,
    MarketplaceReport,
    Message,
    Reservation,
    SellerProfile,
    Favorite,
    SupportAttachment,
    SupportMessage,
    SupportTicket,
    UserAccountState,
    UserActivity,
)
from .scopes import (
    can_manage_listing,
    manageable_goats,
    manageable_listing_q,
    manageable_listings,
)
from .notification_services import (
    create_marketplace_notification,
    notify_marketplace_staff,
)
from .services import (
    accept_reservation,
    cancel_reservation,
    complete_sale,
    confirm_pickup,
    expire_due_reservations,
    expire_reservation,
    log_activity,
    reject_reservation,
    request_pickup,
    request_reservation,
    suggest_pickup,
)
from .support_services import (
    log_user_activity,
    notify_support_reply,
    notify_ticket_created,
    notify_ticket_status_changed,
    save_support_attachment,
)


def _add_model_validation_errors(form, exc):
    """Attach model validation errors without assuming model-only fields exist on the form."""
    if hasattr(exc, "error_dict"):
        for field_name, errors in exc.error_dict.items():
            form_field = field_name if field_name in form.fields else None
            for error in errors:
                form.add_error(form_field, error)
        return
    form.add_error(None, exc)


def _attach_images(listings):
    for listing in listings:
        prefetched = getattr(listing.goat, "marketplace_images", None)
        photos = prefetched if prefetched is not None else listing.goat.images.all()
        listing.display_image = GoatImage.preferred_from(photos)
    return listings


def _trusted_listing_seller_q():
    """Community sellers need approval; the client smart-farm staff do not."""
    return (
        Q(seller__is_staff=True)
        | Q(seller__is_superuser=True)
        | Q(seller__seller_profile__status=SellerProfile.APPROVED)
    )


def _public_listing_queryset():
    return (
        MarketplaceListing.objects.select_related(
            "goat", "seller", "seller__seller_profile"
        )
        .prefetch_related(
            Prefetch(
                "goat__images",
                queryset=GoatImage.objects.only(
                    "id", "goat_id", "image", "angle", "is_primary", "uploaded_at"
                ).order_by("-uploaded_at"),
                to_attr="marketplace_images",
            )
        )
        .filter(
            _trusted_listing_seller_q(),
            goat__status="active",
            goat__is_active=True,
        )
    )


def _save_community_photos(goat, photos):
    for photo in photos:
        GoatImage.objects.filter(goat=goat, is_primary=True).update(is_primary=False)
        GoatImage.objects.create(
            goat=goat,
            image=photo,
            image_type="identification",
            description="Uploaded by community seller",
            is_training_data=False,
            is_primary=True,
        )


def _conversation_inbox_name(user, conversation):
    if user.is_staff:
        return "marketplace:admin_inquiries"
    if conversation.listing.seller_id == user.id:
        return "marketplace:seller_messages"
    return "marketplace:my_inquiries"


def _safe_marketplace_redirect(request, fallback_name, **fallback_kwargs):
    target = request.POST.get("next", "").strip()
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(target)
    return redirect(fallback_name, **fallback_kwargs)


def _mark_saved_listings(user, listings):
    if not getattr(user, "is_authenticated", False):
        for listing in listings:
            listing.is_saved = False
        return listings
    saved_ids = set(
        Favorite.objects.filter(
            user=user,
            listing_id__in=[listing.pk for listing in listings],
        ).values_list("listing_id", flat=True)
    )
    for listing in listings:
        listing.is_saved = listing.pk in saved_ids
    return listings


def marketplace_landing(request):
    expire_due_reservations()
    featured = _public_listing_queryset().filter(
        status=MarketplaceListing.AVAILABLE,
    ).order_by("-is_featured", "-published_at")[:6]
    featured = _mark_saved_listings(request.user, list(featured))
    return render(
        request,
        "marketplace/landing.html",
        {
            "featured_listings": _attach_images(featured),
            "available_count": _public_listing_queryset().filter(
                status=MarketplaceListing.AVAILABLE,
            ).count(),
            "seller_count": _public_listing_queryset().filter(
                status=MarketplaceListing.AVAILABLE,
            ).values("seller_id").distinct().count(),
        },
    )


def marketplace_list(request):
    expire_due_reservations()
    listings = _public_listing_queryset().filter(
        status__in=[MarketplaceListing.AVAILABLE, MarketplaceListing.RESERVED]
    )

    breed = request.GET.get("breed", "").strip()
    gender = request.GET.get("gender", "").strip()
    query = request.GET.get("q", "").strip()
    if query:
        listings = listings.filter(
            Q(goat__goat_id__icontains=query)
            | Q(goat__tag_number__icontains=query)
            | Q(goat__name__icontains=query)
            | Q(goat__breed__icontains=query)
            | Q(sales_description__icontains=query)
            | Q(seller__seller_profile__farm_name__icontains=query)
            | Q(seller__seller_profile__barangay__icontains=query)
            | Q(seller__seller_profile__municipality__icontains=query)
            | Q(seller__seller_profile__province__icontains=query)
        )
    if breed:
        listings = listings.filter(goat__breed=breed)
    if gender:
        listings = listings.filter(goat__gender=gender)

    availability = request.GET.get("availability", "").strip()
    if availability in {MarketplaceListing.AVAILABLE, MarketplaceListing.RESERVED}:
        listings = listings.filter(status=availability)

    location_filters = {
        "barangay": "seller__seller_profile__barangay__iexact",
        "municipality": "seller__seller_profile__municipality__iexact",
        "province": "seller__seller_profile__province__iexact",
    }
    for parameter, lookup in location_filters.items():
        value = request.GET.get(parameter, "").strip()
        if value:
            listings = listings.filter(**{lookup: value})

    seller = request.GET.get("seller", "").strip()
    if seller.isdigit():
        listings = listings.filter(seller__seller_profile__pk=seller)

    numeric_filters = [
        ("min_weight", "goat__weight_kg__gte"),
        ("max_weight", "goat__weight_kg__lte"),
        ("min_price", "price__gte"),
        ("max_price", "price__lte"),
    ]
    for parameter, lookup in numeric_filters:
        raw = request.GET.get(parameter, "").strip()
        if raw:
            try:
                listings = listings.filter(**{lookup: Decimal(raw)})
            except InvalidOperation:
                pass

    today = timezone.localdate()
    try:
        min_age = int(request.GET.get("min_age", ""))
        listings = listings.filter(goat__date_of_birth__lte=today - timedelta(days=min_age * 365))
    except (TypeError, ValueError):
        pass
    try:
        max_age = int(request.GET.get("max_age", ""))
        listings = listings.filter(goat__date_of_birth__gte=today - timedelta(days=(max_age + 1) * 365))
    except (TypeError, ValueError):
        pass

    sort = request.GET.get("sort", "newest")
    sort_options = {
        "newest": ("status", "-published_at"),
        "price_low": ("status", "price"),
        "price_high": ("status", "-price"),
        "weight_low": ("status", "goat__weight_kg"),
        "weight_high": ("status", "-goat__weight_kg"),
        "updated": ("status", "-updated_at"),
    }
    listings = listings.order_by(*sort_options.get(sort, sort_options["newest"]), "-pk")
    paginator = Paginator(listings, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _attach_images(list(page_obj.object_list))
    _mark_saved_listings(request.user, page_obj.object_list)

    public_profiles = SellerProfile.objects.filter(
        Q(status=SellerProfile.APPROVED)
        | Q(user__is_staff=True)
        | Q(user__is_superuser=True),
        user__marketplace_listings__status__in=[
            MarketplaceListing.AVAILABLE,
            MarketplaceListing.RESERVED,
        ]
    ).distinct()
    filter_query = request.GET.copy()
    filter_query.pop("page", None)
    active_filter_names = {
        "q", "breed", "gender", "min_weight", "max_weight", "min_age",
        "max_age", "min_price", "max_price", "barangay", "municipality",
        "province", "availability", "seller",
    }
    return render(
        request,
        "marketplace/list.html",
        {
            "listings": page_obj.object_list,
            "page_obj": page_obj,
            "page_range": paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1),
            "is_paginated": page_obj.has_other_pages(),
            "breed_choices": Goat.BREED_CHOICES,
            "seller_choices": public_profiles.order_by("farm_name"),
            "barangay_choices": public_profiles.exclude(barangay="").order_by("barangay").values_list("barangay", flat=True).distinct(),
            "municipality_choices": public_profiles.exclude(municipality="").order_by("municipality").values_list("municipality", flat=True).distinct(),
            "province_choices": public_profiles.exclude(province="").order_by("province").values_list("province", flat=True).distinct(),
            "selected": request.GET,
            "sort": sort,
            "result_count": paginator.count,
            "filter_query": filter_query.urlencode(),
            "has_active_filters": any(request.GET.get(name) for name in active_filter_names),
        },
    )


def listing_detail(request, pk):
    expire_due_reservations()
    listing = get_object_or_404(
        MarketplaceListing.objects.select_related(
            "goat", "seller", "seller__seller_profile"
        ),
        pk=pk,
    )
    profile = getattr(listing.seller, "seller_profile", None)
    seller_is_trusted = (
        listing.seller.is_staff
        or listing.seller.is_superuser
        or (profile and profile.status == SellerProfile.APPROVED)
    )
    may_preview = request.user.is_authenticated and (
        request.user.is_staff or request.user.id == listing.seller_id
    )
    if (listing.status == MarketplaceListing.DRAFT or not seller_is_trusted) and not may_preview:
        messages.info(request, "That listing is not publicly available.")
        return redirect("marketplace:list")
    if listing.status == MarketplaceListing.DRAFT and not (
        request.user.is_authenticated
        and (request.user.is_staff or request.user.id == listing.seller_id)
    ):
        return redirect("marketplace:list")
    images = listing.goat.images.order_by("-uploaded_at")
    conversation = None
    active_reservation = None
    is_saved = False
    if request.user.is_authenticated and not request.user.is_staff:
        conversation = Conversation.objects.filter(listing=listing, buyer=request.user).first()
        active_reservation = Reservation.objects.filter(
            listing=listing,
            buyer=request.user,
            status__in=[Reservation.PENDING, Reservation.ACCEPTED],
        ).first()
        is_saved = Favorite.objects.filter(
            user=request.user, listing=listing
        ).exists()
    return render(
        request,
        "marketplace/detail.html",
        {
            "listing": listing,
            "images": images,
            "conversation": conversation,
            "active_reservation": active_reservation,
            "is_saved": is_saved,
        },
    )


@login_required
@require_POST
def toggle_favorite(request, pk):
    listing = get_object_or_404(
        MarketplaceListing.objects.select_related("seller").filter(
            _trusted_listing_seller_q()
        ),
        pk=pk,
        status__in=[
            MarketplaceListing.AVAILABLE,
            MarketplaceListing.RESERVED,
        ],
    )
    if listing.seller_id == request.user.pk:
        messages.info(request, "Your own listing is already available in My Listings.")
        return _safe_marketplace_redirect(
            request, "marketplace:detail", pk=listing.pk
        )
    favorite, created = Favorite.objects.get_or_create(
        user=request.user, listing=listing
    )
    if created:
        messages.success(request, "Goat saved to your favorites.")
    else:
        favorite.delete()
        messages.success(request, "Goat removed from your favorites.")
    return _safe_marketplace_redirect(
        request, "marketplace:detail", pk=listing.pk
    )


@login_required
def saved_goats(request):
    favorites = list(
        Favorite.objects.filter(user=request.user)
        .exclude(listing__status=MarketplaceListing.DRAFT)
        .select_related(
            "listing__goat",
            "listing__seller",
            "listing__seller__seller_profile",
        )
        .prefetch_related(
            Prefetch(
                "listing__goat__images",
                queryset=GoatImage.objects.only(
                    "id", "goat_id", "image", "angle", "is_primary", "uploaded_at"
                ).order_by("-uploaded_at"),
                to_attr="marketplace_images",
            )
        )
    )
    listings = _attach_images([favorite.listing for favorite in favorites])
    for listing in listings:
        listing.is_saved = True
    return render(
        request,
        "marketplace/saved_goats.html",
        {"listings": listings},
    )


@login_required
def report_listing(request, pk):
    listing = get_object_or_404(
        MarketplaceListing.objects.select_related("goat", "seller").filter(
            _trusted_listing_seller_q()
        ),
        pk=pk,
        status__in=[
            MarketplaceListing.AVAILABLE,
            MarketplaceListing.RESERVED,
            MarketplaceListing.SOLD,
        ],
    )
    if listing.seller_id == request.user.pk:
        messages.error(request, "You cannot report your own listing.")
        return redirect("marketplace:detail", pk=listing.pk)
    existing = MarketplaceReport.objects.filter(
        reporter=request.user, listing=listing
    ).first()
    if existing:
        messages.info(request, "You already reported this listing.")
        return redirect("marketplace:detail", pk=listing.pk)
    form = MarketplaceReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.reporter = request.user
        report.listing = listing
        try:
            with transaction.atomic():
                report.full_clean()
                report.save()
        except (ValidationError, IntegrityError):
            messages.info(request, "You already reported this listing.")
            return redirect("marketplace:detail", pk=listing.pk)
        log_activity(
            listing,
            request.user,
            "listing_reported",
            report.get_reason_display(),
            metadata={"report_id": report.pk},
        )
        notify_marketplace_staff(
            actor=request.user,
            notification_type=MarketplaceNotification.REPORT,
            title=f"Listing report for {listing.goat.goat_id}",
            message=report.get_reason_display(),
            listing=listing,
            report=report,
            dedup_key=f"listing-report:{report.pk}",
        )
        messages.success(request, "Report submitted for administrator review.")
        return redirect("marketplace:detail", pk=listing.pk)
    return render(
        request,
        "marketplace/report_listing.html",
        {"listing": listing, "form": form},
    )


@login_required
def notifications(request):
    notification_list = MarketplaceNotification.objects.filter(
        recipient=request.user
    ).select_related("listing__goat", "conversation", "reservation", "report")
    paginator = Paginator(notification_list, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "marketplace/notifications.html",
        {"notifications": page_obj.object_list, "page_obj": page_obj},
    )


@login_required
@require_POST
def notification_open(request, pk):
    notification = get_object_or_404(
        MarketplaceNotification.objects.select_related(
            "listing", "conversation", "reservation", "report", "support_ticket"
        ),
        pk=pk,
        recipient=request.user,
    )
    notification.mark_read()
    if notification.support_ticket_id:
        if request.user.is_staff or request.user.is_superuser:
            return redirect(
                "marketplace:admin_support_ticket_detail",
                ticket_number=notification.support_ticket.ticket_number,
            )
        return redirect(
            "marketplace:support_ticket_detail",
            ticket_number=notification.support_ticket.ticket_number,
        )
    if notification.conversation_id:
        return redirect("marketplace:conversation", pk=notification.conversation_id)
    if notification.report_id and request.user.is_staff:
        return redirect("marketplace:admin_reports")
    if notification.reservation_id:
        if notification.reservation.listing.seller_id == request.user.pk:
            return redirect("marketplace:seller_reservations")
        return redirect("marketplace:buyer_reservations")
    if notification.listing_id:
        return redirect("marketplace:detail", pk=notification.listing_id)
    if notification.notification_type == MarketplaceNotification.SELLER_REVIEW:
        return redirect("marketplace:seller_application")
    return redirect("marketplace:notifications")


@login_required
@require_POST
def notifications_read_all(request):
    MarketplaceNotification.objects.filter(
        recipient=request.user, is_read=False
    ).update(is_read=True, read_at=timezone.now())
    messages.success(request, "All marketplace notifications marked as read.")
    return redirect("marketplace:notifications")


@login_required
def complete_profile(request):
    form = ProfileCompletionForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your marketplace profile is ready.")
        return redirect("marketplace:list")
    return render(
        request,
        "marketplace/profile_completion.html",
        {"form": form},
    )


@seller_applicant_required
def seller_application(request):
    profile = SellerProfile.objects.filter(user=request.user).first()
    if profile and profile.status == SellerProfile.SUSPENDED:
        if request.method == "POST":
            messages.error(request, "A suspended seller profile cannot be resubmitted.")
        return render(
            request,
            "marketplace/seller_application.html",
            {"profile": profile, "form": None},
        )

    form = SellerApplicationForm(
        request.POST or None,
        request.FILES or None,
        instance=profile,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        previous_status = profile.status if profile else None
        with transaction.atomic():
            saved = form.save()
            if previous_status in {SellerProfile.APPROVED, SellerProfile.REJECTED}:
                saved.status = SellerProfile.PENDING
                saved.applied_at = timezone.now()
                saved.review_reason = ""
                saved.reviewed_at = None
                saved.reviewed_by = None
                saved.save(
                    update_fields=[
                        "status",
                        "applied_at",
                        "review_reason",
                        "reviewed_at",
                        "reviewed_by",
                        "updated_at",
                    ]
                )
            log_user_activity(
                request.user,
                "seller_application_submitted",
                f"Seller application for {saved.farm_name} submitted.",
                metadata={"seller_profile_id": saved.pk},
            )
        messages.success(request, "Your seller application was submitted for review.")
        notify_marketplace_staff(
            actor=request.user,
            notification_type=MarketplaceNotification.SELLER_REVIEW,
            title=f"Seller application from {saved.farm_name}",
            message="A marketplace user submitted or updated a seller application.",
            dedup_key=f"seller-profile:{saved.pk}:applied:{saved.applied_at.isoformat()}",
        )
        return redirect("marketplace:seller_application")
    return render(
        request,
        "marketplace/seller_application.html",
        {"profile": profile, "form": form},
    )


def seller_public_profile(request, pk):
    profile = get_object_or_404(SellerProfile.objects.select_related("user"), pk=pk)
    may_preview = request.user.is_authenticated and (
        request.user.is_staff or request.user.pk == profile.user_id
    )
    is_trusted_farm_profile = profile.user.is_staff or profile.user.is_superuser
    if profile.status != SellerProfile.APPROVED and not is_trusted_farm_profile and not may_preview:
        messages.info(request, "That seller profile is not publicly available.")
        return redirect("marketplace:list")
    listings = _attach_images(
        list(
            MarketplaceListing.objects.select_related("goat", "seller").filter(
                seller=profile.user,
                status__in=[MarketplaceListing.AVAILABLE, MarketplaceListing.RESERVED],
                goat__status="active",
                goat__is_active=True,
            )
        )
    )
    return render(
        request,
        "marketplace/seller_public_profile.html",
        {
            "profile": profile,
            "listings": listings,
            "active_count": len(listings),
            "sold_count": MarketplaceListing.objects.filter(
                seller=profile.user, status=MarketplaceListing.SOLD
            ).count(),
        },
    )


@approved_seller_required
def seller_dashboard(request):
    expire_due_reservations()
    listings = manageable_listings(request.user)
    conversations = Conversation.objects.filter(listing__in=listings)
    goats = manageable_goats(request.user)
    return render(
        request,
        "marketplace/seller_dashboard.html",
        {
            "profile": seller_profile_for(request.user),
            "goat_count": goats.count(),
            "listing_count": listings.count(),
            "active_count": listings.filter(status=MarketplaceListing.AVAILABLE).count(),
            "reserved_count": listings.filter(status=MarketplaceListing.RESERVED).count(),
            "pending_reservation_count": Reservation.objects.filter(
                manageable_listing_q(request.user, "listing__"),
                status=Reservation.PENDING,
            ).count(),
            "sold_count": listings.filter(status=MarketplaceListing.SOLD).count(),
            "inquiry_count": conversations.count(),
            "unread_count": Message.objects.filter(
                manageable_listing_q(request.user, "conversation__listing__"),
                is_read=False,
            ).exclude(sender=request.user).count(),
        },
    )


@approved_seller_required
def seller_goats(request):
    goats = list(
        manageable_goats(request.user).order_by("-date_added")
    )
    for goat in goats:
        goat.display_image = GoatImage.preferred_from(goat.images.all())
    return render(request, "marketplace/seller_goats.html", {"goats": goats})


@approved_seller_required
def seller_goat_manage(request, pk=None):
    goat = None
    if pk is not None:
        goat = get_object_or_404(
            Goat.all_objects,
            pk=pk,
            owner=request.user,
            record_source=Goat.COMMUNITY,
        )
    listing = getattr(goat, "marketplace_listing", None) if goat else None
    locked = bool(
        listing and listing.status in {MarketplaceListing.RESERVED, MarketplaceListing.SOLD}
    )
    if request.method == "POST" and locked:
        messages.error(request, "Reserved or sold goat records cannot be modified.")
        return redirect("marketplace:seller_goats")

    form = CommunityGoatForm(
        request.POST or None,
        request.FILES or None,
        instance=goat,
        seller=request.user,
    )
    if locked:
        for field in form.fields.values():
            field.disabled = True
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            saved = form.save()
            photos = form.cleaned_data.get("photos", [])
            if saved.images.count() + len(photos) > 10:
                form.add_error("photos", "A goat can have no more than 10 photos.")
                transaction.set_rollback(True)
            else:
                _save_community_photos(saved, photos)
        if not form.errors:
            messages.success(request, f"Goat {saved.goat_id} saved successfully.")
            return redirect("marketplace:seller_goats")
    return render(
        request,
        "marketplace/seller_goat_form.html",
        {
            "form": form,
            "goat": goat,
            "images": goat.images.all() if goat else [],
            "locked": locked,
        },
    )


@approved_seller_required
@require_POST
def seller_goat_image_delete(request, goat_pk, image_pk):
    goat = get_object_or_404(
        Goat.all_objects,
        pk=goat_pk,
        owner=request.user,
        record_source=Goat.COMMUNITY,
    )
    listing = getattr(goat, "marketplace_listing", None)
    if listing and listing.status in {MarketplaceListing.RESERVED, MarketplaceListing.SOLD}:
        messages.error(request, "Photos for a reserved or sold goat cannot be removed.")
        return redirect("marketplace:seller_goat_edit", pk=goat.pk)
    image = get_object_or_404(GoatImage, pk=image_pk, goat=goat)
    if goat.images.count() <= 1 and listing and listing.status == MarketplaceListing.AVAILABLE:
        messages.error(request, "A published listing must keep at least one goat photo.")
        return redirect("marketplace:seller_goat_edit", pk=goat.pk)
    image.delete()
    messages.success(request, "Goat photo removed.")
    return redirect("marketplace:seller_goat_edit", pk=goat.pk)


@approved_seller_required
def seller_listings(request):
    listings = _attach_images(
        list(
            manageable_listings(
                request.user,
                MarketplaceListing.objects.select_related("goat"),
            )
        )
    )
    return render(request, "marketplace/seller_listings.html", {"listings": listings})


@approved_seller_required
def seller_listing_manage(request, pk=None):
    listing = (
        get_object_or_404(
            manageable_listings(
                request.user,
                MarketplaceListing.objects.select_related("goat"),
            ),
            pk=pk,
        )
        if pk
        else None
    )
    if listing and listing.status in {MarketplaceListing.RESERVED, MarketplaceListing.SOLD}:
        messages.error(request, "Reserved or sold listings cannot be edited.")
        return redirect("marketplace:seller_listings")
    initial = None
    if listing is None:
        requested_goat = request.GET.get("goat", "").strip()
        if requested_goat.isdigit() and manageable_goats(
            request.user,
            Goat.all_objects.filter(status="active", is_active=True),
        ).filter(pk=requested_goat).exists():
            initial = {"goat": requested_goat}
    form = ListingForm(
        request.POST or None,
        instance=listing,
        seller=request.user,
        initial=initial,
    )
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        if listing is None:
            saved.seller = request.user
        try:
            saved.full_clean()
        except ValidationError as exc:
            _add_model_validation_errors(form, exc)
        else:
            saved.save()
            log_activity(saved, request.user, "listing_saved", "Seller saved listing details.")
            if listing is None:
                log_user_activity(
                    request.user,
                    "marketplace_listing_created",
                    f"Created marketplace listing for {saved.goat.goat_id}.",
                    metadata={"listing_id": saved.pk},
                )
            messages.success(request, "Listing saved as draft." if not listing else "Listing updated.")
            return redirect("marketplace:seller_listings")
    return render(
        request,
        "marketplace/seller_listing_form.html",
        {"form": form, "listing": listing},
    )


@approved_seller_required
@require_POST
def seller_listing_publication(request, pk):
    with transaction.atomic():
        listing = get_object_or_404(
            manageable_listings(
                request.user,
                MarketplaceListing.objects.select_for_update().select_related("goat"),
            ),
            pk=pk,
        )
        action = request.POST.get("action")
        if action == "publish" and listing.status == MarketplaceListing.DRAFT:
            if not listing.goat.images.exists():
                messages.error(request, "Add at least one goat photo before publishing.")
                return redirect("marketplace:seller_listings")
            listing.status = MarketplaceListing.AVAILABLE
            listing.published_at = timezone.now()
            event = "listing_published"
        elif action == "unpublish" and listing.status == MarketplaceListing.AVAILABLE:
            listing.status = MarketplaceListing.DRAFT
            event = "listing_unpublished"
        else:
            messages.error(request, "That publication change is not allowed.")
            return redirect("marketplace:seller_listings")
        try:
            listing.full_clean()
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
            return redirect("marketplace:seller_listings")
        listing.save(update_fields=["status", "published_at", "updated_at"])
        log_activity(listing, request.user, event)
    messages.success(request, "Listing status updated.")
    return redirect("marketplace:seller_listings")


@login_required
@require_POST
def start_inquiry(request, pk):
    listing = get_object_or_404(
        MarketplaceListing.objects.select_related(
            "goat", "seller__seller_profile"
        ).filter(_trusted_listing_seller_q()),
        pk=pk,
        goat__status="active",
        goat__is_active=True,
    )
    if request.user.is_staff:
        messages.info(request, "Staff can reply from the marketplace administration page.")
        return redirect("marketplace:detail", pk=pk)
    if listing.seller_id == request.user.id:
        messages.error(request, "You cannot inquire about your own listing.")
        return redirect("marketplace:detail", pk=pk)
    if not listing.can_inquire:
        messages.error(request, "This goat is not currently accepting new inquiries.")
        return redirect("marketplace:detail", pk=pk)
    conversation, created = Conversation.objects.get_or_create(listing=listing, buyer=request.user)
    if created:
        log_activity(listing, request.user, "inquiry_started", "Buyer opened a private inquiry.")
        create_marketplace_notification(
            recipient=listing.seller,
            actor=request.user,
            notification_type=MarketplaceNotification.INQUIRY,
            title=f"New inquiry for {listing.goat.goat_id}",
            message=f"{request.user.get_full_name() or request.user.username} opened an inquiry.",
            listing=listing,
            conversation=conversation,
            dedup_key=f"conversation:{conversation.pk}:created",
        )
    return redirect("marketplace:conversation", pk=conversation.pk)


@login_required
def conversation_detail(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related(
            "listing__goat",
            "buyer",
            "listing__seller",
            "listing__seller__seller_profile",
        ),
        pk=pk,
    )
    viewer_is_buyer = conversation.buyer_id == request.user.id
    viewer_is_seller = can_manage_listing(request.user, conversation.listing)
    if not (request.user.is_staff or viewer_is_buyer or viewer_is_seller):
        messages.error(request, "You do not have access to that conversation.")
        return redirect("marketplace:my_inquiries")
    if viewer_is_seller and not is_approved_seller(request.user):
        messages.error(request, "Seller messaging is unavailable for this account.")
        return redirect("marketplace:seller_application")

    can_message = (viewer_is_buyer or viewer_is_seller) and conversation.status == Conversation.OPEN

    if request.method == "POST":
        form = MessageForm(request.POST)
        if not can_message:
            messages.error(request, "This conversation is closed or read-only.")
        elif form.is_valid():
            message = form.save(commit=False)
            message.conversation = conversation
            message.sender = request.user
            try:
                message.full_clean()
            except ValidationError as exc:
                _add_model_validation_errors(form, exc)
            else:
                message.save()
                Conversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
                recipient = (
                    conversation.listing.seller
                    if viewer_is_buyer
                    else conversation.buyer
                )
                create_marketplace_notification(
                    recipient=recipient,
                    actor=request.user,
                    notification_type=MarketplaceNotification.MESSAGE,
                    title=f"New message about {conversation.listing.goat.goat_id}",
                    message=message.body,
                    listing=conversation.listing,
                    conversation=conversation,
                    dedup_key=f"message:{message.pk}",
                )
                return redirect("marketplace:conversation", pk=pk)
    else:
        form = MessageForm()

    if viewer_is_buyer or viewer_is_seller:
        conversation.messages.exclude(sender=request.user).filter(is_read=False).update(is_read=True)
    expire_due_reservations()
    active_reservation = conversation.reservations.filter(
        status__in=[Reservation.PENDING, Reservation.ACCEPTED]
    ).first()
    return render(
        request,
        "marketplace/conversation.html",
        {
            "conversation": conversation,
            "conversation_messages": conversation.messages.select_related("sender"),
            "form": form,
            "active_reservation": active_reservation,
            "viewer_is_buyer": viewer_is_buyer,
            "viewer_is_seller": viewer_is_seller,
            "can_message": can_message,
            "inbox_name": _conversation_inbox_name(request.user, conversation),
        },
    )


@login_required
def my_inquiries(request):
    conversations = (
        Conversation.objects.filter(buyer=request.user)
        .select_related("listing__goat", "listing__seller__seller_profile")
        .annotate(
            message_count=Count("messages"),
            unread_count=Count(
                "messages",
                filter=Q(messages__is_read=False) & ~Q(messages__sender=request.user),
            ),
        )
    )
    return render(request, "marketplace/my_inquiries.html", {"conversations": conversations})


@approved_seller_required
def seller_messages(request):
    conversations = (
        Conversation.objects.filter(manageable_listing_q(request.user, "listing__"))
        .select_related("listing__goat", "buyer")
        .annotate(
            message_count=Count("messages"),
            unread_count=Count(
                "messages",
                filter=Q(messages__is_read=False) & ~Q(messages__sender=request.user),
            ),
        )
    )
    return render(
        request,
        "marketplace/seller_messages.html",
        {"conversations": conversations},
    )


@login_required
@require_POST
def conversation_status(request, pk):
    with transaction.atomic():
        conversation = get_object_or_404(
            Conversation.objects.select_for_update().select_related("listing"), pk=pk
        )
        viewer_is_seller = can_manage_listing(request.user, conversation.listing)
        authorized = request.user.is_staff or conversation.buyer_id == request.user.id or viewer_is_seller
        if not authorized:
            messages.error(request, "You do not have access to that conversation.")
            return redirect("marketplace:my_inquiries")
        if viewer_is_seller and not is_approved_seller(request.user):
            messages.error(request, "Seller messaging is unavailable for this account.")
            return redirect("marketplace:seller_application")

        action = request.POST.get("action")
        if action == "close" and conversation.status == Conversation.OPEN:
            conversation.status = Conversation.CLOSED
            conversation.closed_at = timezone.now()
            conversation.closed_by = request.user
            notice = "Conversation closed."
        elif action == "reopen" and conversation.status == Conversation.CLOSED:
            conversation.status = Conversation.OPEN
            conversation.closed_at = None
            conversation.closed_by = None
            notice = "Conversation reopened."
        else:
            messages.error(request, "That conversation status change is not allowed.")
            return redirect("marketplace:conversation", pk=conversation.pk)
        conversation.save(
            update_fields=["status", "closed_at", "closed_by", "updated_at"]
        )
    messages.success(request, notice)
    return redirect("marketplace:conversation", pk=conversation.pk)


@login_required
@require_POST
def confirm_purchase(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related("listing"), pk=pk, buyer=request.user
    )
    try:
        request_reservation(
            conversation.listing_id, request.user, conversation
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(
            request,
            "Reservation request sent. The listing stays available until the seller accepts.",
        )
        return redirect("marketplace:buyer_reservations")
    return redirect("marketplace:conversation", pk=pk)


@login_required
def pickup_request(request, pk):
    reservation = get_object_or_404(
        Reservation.objects.select_related("listing__goat", "buyer"),
        pk=pk,
        buyer=request.user,
    )
    expire_due_reservations()
    reservation.refresh_from_db()
    if reservation.status != Reservation.ACCEPTED:
        messages.info(request, "Pickup can be arranged after the seller accepts.")
        return redirect("marketplace:buyer_reservations")

    form = PickupRequestForm(request.POST or None, instance=reservation)
    if request.method == "POST" and form.is_valid():
        request_pickup(
            reservation.pk,
            request.user,
            form.cleaned_data["pickup_datetime"],
            form.cleaned_data["pickup_notes"],
        )
        messages.success(request, "Pickup proposal sent to the seller.")
        return redirect("marketplace:buyer_reservations")
    return render(request, "marketplace/pickup_form.html", {"reservation": reservation, "form": form})


@login_required
def buyer_reservations(request):
    expire_due_reservations()
    reservations = Reservation.objects.filter(buyer=request.user).select_related(
        "listing__goat", "listing__seller__seller_profile", "conversation"
    )
    return render(
        request,
        "marketplace/buyer_reservations.html",
        {"reservations": reservations},
    )


@approved_seller_required
def seller_reservations(request):
    expire_due_reservations()
    reservations = Reservation.objects.filter(
        manageable_listing_q(request.user, "listing__")
    ).select_related("listing__goat", "buyer", "conversation")
    profile = seller_profile_for(request.user)
    return render(
        request,
        "marketplace/seller_reservations.html",
        {
            "reservations": reservations,
            # Farm Owners manage the system farm directly and do not need a
            # community SellerProfile application.
            "profile": profile,
            "default_pickup_location": profile.address_details if profile else "",
        },
    )


@login_required
@require_POST
def reservation_action(request, pk):
    reservation = get_object_or_404(
        Reservation.objects.select_related(
            "listing__seller__seller_profile", "buyer", "conversation"
        ),
        pk=pk,
    )
    viewer_is_buyer = reservation.buyer_id == request.user.pk
    viewer_is_seller = can_manage_listing(request.user, reservation.listing)
    # Staff moderation has a separate, deliberately limited endpoint below.
    # Do not let staff impersonate a buyer or a community listing seller here.
    if not (viewer_is_buyer or viewer_is_seller):
        raise PermissionDenied("You do not have access to that reservation.")

    action = request.POST.get("action")
    try:
        if action == "accept":
            form = ReservationAcceptanceForm(request.POST)
            if not form.is_valid():
                raise ValidationError("Enter a valid reservation expiration.")
            accept_reservation(
                pk,
                request.user,
                form.cleaned_data["expires_at"],
                form.cleaned_data["pickup_location"],
            )
            messages.success(request, "Reservation accepted. The goat is now Reserved.")
        elif action == "reject":
            reject_reservation(
                pk, request.user, request.POST.get("reason", "").strip()
            )
            messages.success(request, "Reservation request rejected.")
        elif action == "cancel":
            cancel_reservation(
                pk, request.user, request.POST.get("reason", "").strip()
            )
            messages.success(request, "Reservation cancelled.")
        elif action == "suggest_pickup":
            form = SellerPickupSuggestionForm(request.POST, instance=reservation)
            if not form.is_valid():
                raise ValidationError("Enter a valid alternative pickup schedule.")
            suggest_pickup(
                pk,
                request.user,
                form.cleaned_data["pickup_datetime"],
                form.cleaned_data["pickup_notes"],
                form.cleaned_data["pickup_location"],
            )
            messages.success(request, "Alternative pickup schedule sent to the buyer.")
        elif action == "confirm_pickup":
            confirm_pickup(pk, request.user)
            messages.success(request, "Pickup schedule confirmed.")
        elif action == "complete":
            complete_sale(pk, request.user)
            messages.success(
                request, "Sale completed and the goat was retained in sales history."
            )
        elif action == "expire":
            if not viewer_is_seller:
                raise PermissionDenied("Only the listing seller can expire a hold here.")
            if not expire_reservation(pk):
                raise ValidationError("This reservation is not due to expire.")
            messages.success(request, "Reservation expired and listing returned to Available.")
        else:
            raise ValidationError("Unknown reservation action.")
    except (PermissionDenied, ValidationError) as exc:
        error = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
        messages.error(request, error)

    if viewer_is_seller:
        return redirect("marketplace:seller_reservations")
    if viewer_is_buyer:
        return redirect("marketplace:buyer_reservations")
    return redirect("marketplace:admin_dashboard")


@staff_required
def admin_dashboard(request):
    expire_due_reservations()
    listing_queryset = MarketplaceListing.objects.select_related(
        "goat", "seller"
    ).prefetch_related(
        Prefetch(
            "goat__images",
            queryset=GoatImage.objects.only(
                "id", "goat_id", "image", "angle", "is_primary", "uploaded_at"
            ).order_by("-uploaded_at"),
            to_attr="marketplace_images",
        )
    )
    listing_page = Paginator(listing_queryset, 25).get_page(
        request.GET.get("listings_page")
    )
    listings = _attach_images(list(listing_page.object_list))

    reservation_queryset = Reservation.objects.select_related(
        "listing__goat", "listing__seller", "buyer"
    ).filter(status__in=[Reservation.PENDING, Reservation.ACCEPTED])
    reservation_counts = reservation_queryset.aggregate(
        reserved=Count("id", filter=Q(status=Reservation.ACCEPTED)),
        pending=Count("id", filter=Q(status=Reservation.PENDING)),
    )
    reservation_page = Paginator(reservation_queryset, 25).get_page(
        request.GET.get("reservations_page")
    )
    listing_counts = MarketplaceListing.objects.aggregate(
        available=Count("id", filter=Q(status=MarketplaceListing.AVAILABLE)),
        sold=Count("id", filter=Q(status=MarketplaceListing.SOLD)),
    )
    return render(
        request,
        "marketplace/admin_dashboard.html",
        {
            "listings": listings,
            "listing_page": listing_page,
            "reservations": reservation_page.object_list,
            "reservation_page": reservation_page,
            "available_count": listing_counts["available"],
            "reserved_count": reservation_counts["reserved"],
            "pending_reservation_count": reservation_counts["pending"],
            "sold_count": listing_counts["sold"],
            "inquiry_count": Conversation.objects.count(),
            "pending_seller_count": SellerProfile.objects.filter(
                status=SellerProfile.PENDING,
                user__is_staff=False,
                user__is_superuser=False,
            ).count(),
            "pending_report_count": MarketplaceReport.objects.filter(
                status=MarketplaceReport.PENDING
            ).count(),
            "registered_user_count": get_user_model().objects.count(),
            "open_support_count": SupportTicket.objects.filter(
                status__in=[
                    SupportTicket.OPEN,
                    SupportTicket.IN_PROGRESS,
                    SupportTicket.WAITING_CUSTOMER,
                ]
            ).count(),
        },
    )


@staff_required
def seller_applications_admin(request):
    selected_status = request.GET.get("status", SellerProfile.PENDING)
    valid_statuses = {choice[0] for choice in SellerProfile.STATUS_CHOICES}
    profiles = (
        SellerProfile.objects.select_related("user", "reviewed_by")
        .filter(user__is_staff=False, user__is_superuser=False)
        .annotate(listing_count=Count("user__marketplace_listings"))
    )
    if selected_status in valid_statuses:
        profiles = profiles.filter(status=selected_status)
    else:
        selected_status = "all"
    query = request.GET.get("q", "").strip()
    if query:
        profiles = profiles.filter(
            Q(farm_name__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__email__icontains=query)
            | Q(municipality__icontains=query)
            | Q(province__icontains=query)
        )
    return render(
        request,
        "marketplace/seller_applications_admin.html",
        {
            "profiles": profiles,
            "selected_status": selected_status,
            "status_choices": SellerProfile.STATUS_CHOICES,
            "query": query,
            "status_counts": {
                status: SellerProfile.objects.filter(
                    status=status,
                    user__is_staff=False,
                    user__is_superuser=False,
                ).count()
                for status, _ in SellerProfile.STATUS_CHOICES
            },
        },
    )


@staff_required
@require_POST
def seller_application_action(request, pk):
    with transaction.atomic():
        profile = get_object_or_404(
            SellerProfile.objects.select_for_update().select_related("user"), pk=pk
        )
        action = request.POST.get("action")
        reason = request.POST.get("reason", "").strip()
        applicant_is_staff = profile.user.is_staff or profile.user.is_superuser
        if applicant_is_staff:
            messages.error(
                request,
                "Staff-owned farm profiles are not community seller applications and cannot be reviewed here.",
            )
            return redirect("marketplace:seller_applications_admin")
        if profile.user_id == request.user.id:
            messages.error(request, "Administrators cannot review their own seller profile.")
            return redirect("marketplace:seller_applications_admin")

        transitions = {
            "approve": (
                {SellerProfile.PENDING, SellerProfile.REJECTED, SellerProfile.SUSPENDED},
                SellerProfile.APPROVED,
            ),
            "reject": ({SellerProfile.PENDING}, SellerProfile.REJECTED),
            "suspend": ({SellerProfile.APPROVED}, SellerProfile.SUSPENDED),
        }
        transition = transitions.get(action)
        if not transition or profile.status not in transition[0]:
            messages.error(request, "That seller status change is not allowed.")
            return redirect("marketplace:seller_applications_admin")
        if action in {"reject", "suspend"} and not reason:
            messages.error(request, "A reason is required for rejection or suspension.")
            return redirect("marketplace:seller_applications_admin")

        profile.status = transition[1]
        profile.review_reason = reason
        profile.reviewed_by = request.user
        profile.reviewed_at = timezone.now()
        if action == "approve":
            profile.approved_at = timezone.now()
        profile.save(
            update_fields=[
                "status",
                "review_reason",
                "reviewed_by",
                "reviewed_at",
                "approved_at",
                "updated_at",
            ]
        )
        if action == "suspend":
            active_listings = MarketplaceListing.objects.select_for_update().filter(
                seller=profile.user,
                status=MarketplaceListing.AVAILABLE,
            )
            for listing in active_listings:
                listing.status = MarketplaceListing.DRAFT
                listing.save(update_fields=["status", "updated_at"])
                log_activity(
                    listing,
                    request.user,
                    "listing_unpublished_seller_suspended",
                    reason,
                )
        seller_events = {
            "approve": "seller_application_approved",
            "reject": "seller_application_declined",
            "suspend": "seller_account_suspended",
        }
        log_user_activity(
            profile.user,
            seller_events[action],
            reason or f"Seller status changed to {profile.get_status_display()}.",
            actor=request.user,
            metadata={"seller_profile_id": profile.pk},
        )
    success_messages = {
        "approve": "Seller approved successfully.",
        "reject": "Seller application declined successfully.",
        "suspend": "Seller suspended successfully.",
    }
    notification_titles = {
        "approve": "Your seller application was approved",
        "reject": "Your seller application was declined",
        "suspend": "Your seller account was suspended",
    }
    create_marketplace_notification(
        recipient=profile.user,
        actor=request.user,
        notification_type=MarketplaceNotification.SELLER_REVIEW,
        title=notification_titles[action],
        message=profile.review_reason
        or "Open your seller application to review the current status.",
        dedup_key=(
            f"seller-profile:{profile.pk}:{action}:"
            f"{profile.reviewed_at.isoformat()}"
        ),
    )
    messages.success(request, success_messages[action])
    return redirect("marketplace:seller_applications_admin")


@staff_required
def manage_listing(request, pk=None):
    listing = get_object_or_404(MarketplaceListing, pk=pk) if pk else None
    form = ListingForm(request.POST or None, instance=listing, seller=request.user)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        if not saved.pk:
            saved.seller = request.user
        saved.full_clean()
        saved.save()
        log_activity(saved, request.user, "listing_saved", "Marketplace listing details saved.")
        messages.success(request, "Marketplace listing saved.")
        return redirect("marketplace:admin_dashboard")
    return render(request, "marketplace/listing_form.html", {"form": form, "listing": listing})


@staff_required
@require_POST
def set_listing_publication(request, pk):
    with transaction.atomic():
        listing = get_object_or_404(
            MarketplaceListing.objects.select_for_update().select_related("goat"), pk=pk
        )
        action = request.POST.get("action")
        if action == "publish" and listing.status == MarketplaceListing.DRAFT:
            if listing.goat.status != "active" or not listing.goat.is_active:
                messages.error(request, "Only an active inventory goat can be published.")
                return redirect("marketplace:admin_dashboard")
            listing.status = MarketplaceListing.AVAILABLE
            listing.published_at = timezone.now()
            event = "listing_published"
        elif action == "unpublish" and listing.status == MarketplaceListing.AVAILABLE:
            listing.status = MarketplaceListing.DRAFT
            event = "listing_unpublished"
        else:
            messages.error(request, "That publication change is not allowed for this listing.")
            return redirect("marketplace:admin_dashboard")
        try:
            listing.full_clean()
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
            return redirect("marketplace:admin_dashboard")
        listing.save(update_fields=["status", "published_at", "updated_at"])
        log_activity(listing, request.user, event)
    messages.success(request, "Listing status updated.")
    return redirect("marketplace:admin_dashboard")


@staff_required
@require_POST
def set_listing_featured(request, pk):
    action = request.POST.get("action", "")
    with transaction.atomic():
        listing = get_object_or_404(
            MarketplaceListing.objects.select_for_update().select_related(
                "goat", "seller", "seller__seller_profile"
            ),
            pk=pk,
        )
        if action == "feature":
            is_publicly_available = (
                listing.status == MarketplaceListing.AVAILABLE
                and _public_listing_queryset().filter(pk=listing.pk).exists()
            )
            if not is_publicly_available:
                messages.error(
                    request,
                    "Only a publicly available goat can be featured on the homepage.",
                )
                return redirect("marketplace:admin_dashboard")
            list(
                MarketplaceListing.objects.select_for_update()
                .filter(is_featured=True)
                .values_list("pk", flat=True)
            )
            MarketplaceListing.objects.filter(is_featured=True).exclude(
                pk=listing.pk
            ).update(is_featured=False)
            listing.is_featured = True
            listing.save(update_fields=["is_featured", "updated_at"])
            log_activity(
                listing,
                request.user,
                "listing_featured",
                "Selected as the marketplace homepage feature.",
            )
            messages.success(
                request,
                f"{listing.goat.goat_id} is now featured on the marketplace homepage.",
            )
        elif action == "unfeature" and listing.is_featured:
            listing.is_featured = False
            listing.save(update_fields=["is_featured", "updated_at"])
            log_activity(
                listing,
                request.user,
                "listing_unfeatured",
                "Removed from the marketplace homepage feature.",
            )
            messages.success(request, "Homepage feature removed.")
        else:
            messages.error(request, "That featured-listing change is not allowed.")
    return redirect("marketplace:admin_dashboard")


@staff_required
def admin_inquiries(request):
    conversations = Conversation.objects.select_related(
        "listing__goat", "listing__seller", "buyer"
    ).annotate(message_count=Count("messages"))
    return render(request, "marketplace/admin_inquiries.html", {"conversations": conversations})


@staff_required
def admin_reports(request):
    selected_status = request.GET.get("status", MarketplaceReport.PENDING)
    reports = MarketplaceReport.objects.select_related(
        "listing__goat", "listing__seller", "reporter", "reviewed_by"
    )
    valid_statuses = {status for status, _ in MarketplaceReport.STATUS_CHOICES}
    if selected_status in valid_statuses:
        reports = reports.filter(status=selected_status)
    else:
        selected_status = "all"
    return render(
        request,
        "marketplace/admin_reports.html",
        {
            "reports": reports,
            "selected_status": selected_status,
            "status_filters": [
                {
                    "value": status,
                    "label": label,
                    "count": MarketplaceReport.objects.filter(status=status).count(),
                }
                for status, label in MarketplaceReport.STATUS_CHOICES
            ],
        },
    )


@staff_required
@require_POST
def admin_report_action(request, pk):
    with transaction.atomic():
        report = get_object_or_404(
            MarketplaceReport.objects.select_for_update().select_related(
                "listing__goat", "reporter"
            ),
            pk=pk,
        )
        action = request.POST.get("action")
        notes = request.POST.get("notes", "").strip()
        if action == "review":
            target_status = MarketplaceReport.REVIEWING
        elif action == "resolve":
            target_status = MarketplaceReport.RESOLVED
        elif action == "dismiss":
            target_status = MarketplaceReport.DISMISSED
        elif action == "hide":
            if report.listing.status == MarketplaceListing.RESERVED:
                messages.error(
                    request,
                    "Cancel the active reservation before hiding this listing.",
                )
                return redirect("marketplace:admin_reports")
            if report.listing.status == MarketplaceListing.AVAILABLE:
                report.listing.status = MarketplaceListing.DRAFT
                report.listing.save(update_fields=["status", "updated_at"])
                log_activity(
                    report.listing,
                    request.user,
                    "listing_hidden_after_report",
                    notes or report.get_reason_display(),
                    metadata={"report_id": report.pk},
                )
            target_status = MarketplaceReport.RESOLVED
        else:
            messages.error(request, "Unknown report action.")
            return redirect("marketplace:admin_reports")

        report.status = target_status
        report.reviewed_at = timezone.now()
        report.reviewed_by = request.user
        report.resolution_notes = notes
        report.save(
            update_fields=[
                "status",
                "reviewed_at",
                "reviewed_by",
                "resolution_notes",
            ]
        )
    if action == "hide" and report.listing.status == MarketplaceListing.DRAFT:
        create_marketplace_notification(
            recipient=report.listing.seller,
            actor=request.user,
            notification_type=MarketplaceNotification.LISTING,
            title=f"Listing {report.listing.goat.goat_id} was hidden",
            message=notes or "An administrator hid this listing after reviewing a report.",
            listing=report.listing,
            report=report,
            dedup_key=f"listing-report:{report.pk}:seller-hidden",
        )
    create_marketplace_notification(
        recipient=report.reporter,
        actor=request.user,
        notification_type=MarketplaceNotification.REPORT,
        title=f"Your report for {report.listing.goat.goat_id} was reviewed",
        message=notes or report.get_status_display(),
        listing=report.listing,
        report=report,
        dedup_key=f"listing-report:{report.pk}:{action}",
    )
    messages.success(request, "Marketplace report updated.")
    return redirect("marketplace:admin_reports")


@staff_required
@require_POST
def admin_reservation_action(request, pk):
    get_object_or_404(
        Reservation.objects.select_related("listing"), pk=pk
    )
    action = request.POST.get("action")
    try:
        if action == "cancel":
            cancel_reservation(pk, request.user, request.POST.get("reason", "").strip())
            messages.success(request, "Reservation cancelled by marketplace moderation.")
        elif action == "expire":
            if not expire_reservation(pk):
                raise ValidationError("This reservation is not due to expire.")
            messages.success(request, "Expired reservation released.")
        else:
            messages.error(
                request,
                "Buyer-seller transaction decisions must be made by the listing seller.",
            )
    except (PermissionDenied, ValidationError) as exc:
        error = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
        messages.error(request, error)
    return redirect("marketplace:admin_dashboard")


@staff_required
def sales_history(request):
    sales = Reservation.objects.filter(status=Reservation.COMPLETED).select_related(
        "listing__goat", "buyer", "completed_by"
    )
    activity = MarketplaceActivity.objects.select_related("listing__goat", "actor")[:100]
    return render(request, "marketplace/sales_history.html", {"sales": sales, "activity": activity})


@login_required
def buyer_purchase_history(request):
    sales = Reservation.objects.filter(
        buyer=request.user, status=Reservation.COMPLETED
    ).select_related("listing__goat", "listing__seller__seller_profile")
    return render(
        request,
        "marketplace/buyer_purchase_history.html",
        {"sales": sales},
    )


@approved_seller_required
def seller_sales_history(request):
    sales = Reservation.objects.filter(
        manageable_listing_q(request.user, "listing__"),
        status=Reservation.COMPLETED,
    ).select_related("listing__goat", "buyer")
    return render(
        request,
        "marketplace/seller_sales_history.html",
        {"sales": sales},
    )


def _account_role(user):
    group_names = {group.name for group in user.groups.all()}
    profile = getattr(user, "seller_profile", None)
    if user.is_superuser:
        return "Administrator"
    if user.is_staff:
        return "Staff"
    if "Farm Owners" in group_names:
        return "Farm Owner"
    if "Farm Operators" in group_names:
        return "Farm Operator"
    if profile and profile.status == SellerProfile.APPROVED:
        return "Seller / Buyer"
    return "Buyer"


def _account_status(user):
    state = getattr(user, "marketplace_account_state", None)
    if state:
        return state.status, state.get_status_display()
    return (
        (UserAccountState.ACTIVE, "Active")
        if user.is_active
        else (UserAccountState.DEACTIVATED, "Deactivated")
    )


@staff_required
def registered_users_admin(request):
    User = get_user_model()
    users = (
        User.objects.select_related(
            "marketplace_account_state", "seller_profile"
        )
        .prefetch_related("groups")
        .order_by("-date_joined")
    )
    query = request.GET.get("q", "").strip()
    if query:
        for term in query.split():
            users = users.filter(
                Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
                | Q(email__icontains=term)
                | Q(username__icontains=term)
            )

    role = request.GET.get("role", "").strip()
    if role == "admin":
        users = users.filter(is_superuser=True)
    elif role == "staff":
        users = users.filter(is_staff=True, is_superuser=False)
    elif role == "farm_owner":
        users = users.filter(groups__name=FARM_OWNER_GROUP_NAME)
    elif role == "farm_operator":
        users = users.filter(groups__name=FARM_OPERATOR_GROUP_NAME)
    elif role == "seller":
        users = users.filter(
            seller_profile__status=SellerProfile.APPROVED,
            is_staff=False,
        )
    elif role == "buyer":
        users = users.filter(groups__name="Marketplace Buyers", is_staff=False)

    account_status = request.GET.get("account_status", "").strip()
    if account_status in {
        UserAccountState.ACTIVE,
        UserAccountState.DEACTIVATED,
        UserAccountState.SUSPENDED,
    }:
        users = users.filter(marketplace_account_state__status=account_status)

    seller_status = request.GET.get("seller_status", "").strip()
    valid_seller_statuses = {value for value, _ in SellerProfile.STATUS_CHOICES}
    if seller_status in valid_seller_statuses:
        users = users.filter(seller_profile__status=seller_status)
    elif seller_status == "none":
        users = users.filter(seller_profile__isnull=True)

    for field_name, lookup in (
        ("registered_from", "date_joined__date__gte"),
        ("registered_to", "date_joined__date__lte"),
    ):
        value = request.GET.get(field_name, "").strip()
        if value:
            try:
                timezone.datetime.fromisoformat(value)
            except ValueError:
                messages.error(request, "Use a valid registration date.")
            else:
                users = users.filter(**{lookup: value})

    users = users.distinct()
    paginator = Paginator(users, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    for account in page_obj.object_list:
        account.admin_role = _account_role(account)
        account.admin_status, account.admin_status_label = _account_status(account)
        profile = getattr(account, "seller_profile", None)
        account.admin_seller_status = (
            profile.get_status_display() if profile else "Not a seller"
        )
    return render(
        request,
        "marketplace/admin_registered_users.html",
        {
            "accounts": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
            "selected_role": role,
            "selected_account_status": account_status,
            "selected_seller_status": seller_status,
            "account_status_choices": UserAccountState.STATUS_CHOICES,
            "seller_status_choices": SellerProfile.STATUS_CHOICES,
        },
    )


@staff_required
def registered_user_detail_admin(request, pk):
    User = get_user_model()
    account = get_object_or_404(
        User.objects.select_related(
            "marketplace_account_state", "seller_profile"
        ).prefetch_related("groups"),
        pk=pk,
    )
    account.admin_role = _account_role(account)
    account.admin_status, account.admin_status_label = _account_status(account)
    seller_profile = getattr(account, "seller_profile", None)
    related_reservations = Reservation.objects.filter(
        Q(buyer=account) | Q(listing__seller=account)
    ).select_related("listing__goat", "buyer")[:20]
    return render(
        request,
        "marketplace/admin_registered_user_detail.html",
        {
            "account": account,
            "seller_profile_detail": seller_profile,
            "listings": MarketplaceListing.objects.filter(seller=account)
            .select_related("goat")
            .order_by("-created_at")[:20],
            "reservations": related_reservations,
            "support_tickets": SupportTicket.objects.filter(user=account)[:20],
            "activity": UserActivity.objects.filter(user=account)
            .select_related("actor")[:50],
        },
    )


@staff_required
@require_POST
def registered_user_action_admin(request, pk):
    User = get_user_model()
    with transaction.atomic():
        account = get_object_or_404(User.objects.select_for_update(), pk=pk)
        if account.pk == request.user.pk:
            messages.error(request, "You cannot change your own account status.")
            return redirect("marketplace:registered_user_detail_admin", pk=pk)
        if (account.is_staff or account.is_superuser) and not request.user.is_superuser:
            messages.error(request, "Only a superuser can manage another staff account.")
            return redirect("marketplace:registered_user_detail_admin", pk=pk)

        state, _ = UserAccountState.objects.select_for_update().get_or_create(
            user=account,
            defaults={
                "status": (
                    UserAccountState.ACTIVE
                    if account.is_active
                    else UserAccountState.DEACTIVATED
                )
            },
        )
        action = request.POST.get("action", "").strip()
        reason = request.POST.get("reason", "").strip()
        if action == "assign_role":
            role = request.POST.get("role", "").strip()
            role_groups = {
                "farm_owner": FARM_OWNER_GROUP_NAME,
                "farm_operator": FARM_OPERATOR_GROUP_NAME,
                "marketplace": BUYER_GROUP_NAME,
            }
            if role not in role_groups:
                messages.error(request, "Select a valid account role.")
                return redirect("marketplace:registered_user_detail_admin", pk=pk)
            managed_groups = Group.objects.filter(
                name__in=[
                    FARM_OWNER_GROUP_NAME,
                    FARM_OPERATOR_GROUP_NAME,
                    BUYER_GROUP_NAME,
                ]
            )
            account.groups.remove(*managed_groups)
            selected_group, _ = Group.objects.get_or_create(name=role_groups[role])
            account.groups.add(selected_group)
            log_user_activity(
                account,
                "account_role_changed",
                f"Role changed to {role.replace('_', ' ')} by an administrator.",
                actor=request.user,
            )
            messages.success(request, "Account role updated successfully.")
            return redirect("marketplace:registered_user_detail_admin", pk=pk)
        transitions = {
            "deactivate": (
                {UserAccountState.ACTIVE},
                UserAccountState.DEACTIVATED,
                False,
            ),
            "suspend": (
                {UserAccountState.ACTIVE},
                UserAccountState.SUSPENDED,
                False,
            ),
            "activate": (
                {UserAccountState.DEACTIVATED},
                UserAccountState.ACTIVE,
                True,
            ),
            "restore": (
                {UserAccountState.SUSPENDED},
                UserAccountState.ACTIVE,
                True,
            ),
        }
        transition = transitions.get(action)
        if not transition or state.status not in transition[0]:
            messages.error(request, "That account status change is not allowed.")
            return redirect("marketplace:registered_user_detail_admin", pk=pk)
        if action in {"deactivate", "suspend"} and not reason:
            messages.error(request, "A reason is required for this account action.")
            return redirect("marketplace:registered_user_detail_admin", pk=pk)

        state.status = transition[1]
        state.reason = reason
        state.changed_by = request.user
        state.save(update_fields=["status", "reason", "changed_by", "changed_at"])
        account.is_active = transition[2]
        account.save(update_fields=["is_active"])
        if not account.is_active:
            MarketplaceListing.objects.filter(
                seller=account, status=MarketplaceListing.AVAILABLE
            ).update(status=MarketplaceListing.DRAFT, updated_at=timezone.now())
        log_user_activity(
            account,
            f"account_{action}d" if action != "restore" else "account_restored",
            reason or f"Account {action}d by an administrator.",
            actor=request.user,
        )
    messages.success(request, f"Account {action} completed successfully.")
    return redirect("marketplace:registered_user_detail_admin", pk=pk)


def _support_reference_context(request):
    listing = conversation = reservation = None
    if request.GET.get("conversation"):
        conversation = get_object_or_404(
            Conversation.objects.select_related("listing"),
            pk=request.GET["conversation"],
        )
        if not conversation.user_is_participant(request.user):
            raise PermissionDenied("You do not have access to that marketplace conversation.")
        listing = conversation.listing
    if request.GET.get("reservation"):
        reservation = get_object_or_404(
            Reservation.objects.select_related("listing", "conversation"),
            pk=request.GET["reservation"],
        )
        if request.user.pk not in {
            reservation.buyer_id,
            reservation.listing.seller_id,
        }:
            raise PermissionDenied("You do not have access to that reservation.")
        listing = reservation.listing
        conversation = reservation.conversation
    if request.GET.get("listing") and not listing:
        listing = get_object_or_404(MarketplaceListing, pk=request.GET["listing"])
    return listing, conversation, reservation


@login_required
def support_center(request):
    tickets = SupportTicket.objects.filter(user=request.user)
    status = request.GET.get("status", "").strip()
    if status in {value for value, _ in SupportTicket.STATUS_CHOICES}:
        tickets = tickets.filter(status=status)
    paginator = Paginator(tickets, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "marketplace/support_center.html",
        {"tickets": page_obj.object_list, "page_obj": page_obj, "selected_status": status},
    )


@login_required
def support_ticket_create(request):
    listing, conversation, reservation = _support_reference_context(request)
    initial = {}
    if reservation:
        initial = {
            "category": SupportTicket.RESERVATION,
            "subject": f"Help with reservation for {reservation.listing.goat.goat_id}",
        }
    elif conversation:
        initial = {
            "category": SupportTicket.MARKETPLACE,
            "subject": f"Help with marketplace conversation #{conversation.pk}",
        }
    elif listing:
        initial = {
            "category": SupportTicket.MARKETPLACE,
            "subject": f"Help with listing {listing.goat.goat_id}",
        }
    form = SupportTicketForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            ticket = form.save(commit=False)
            ticket.user = request.user
            ticket.related_listing = listing
            ticket.related_conversation = conversation
            ticket.related_reservation = reservation
            ticket.full_clean()
            ticket.save()
            opening_message = SupportMessage(
                ticket=ticket,
                sender=request.user,
                body=ticket.description,
            )
            opening_message.full_clean()
            opening_message.save()
            save_support_attachment(
                opening_message, form.cleaned_data.get("attachment")
            )
            log_user_activity(
                request.user,
                "support_ticket_created",
                f"Created support ticket {ticket.ticket_number}.",
                metadata={"ticket_id": ticket.pk},
            )
        notify_ticket_created(ticket)
        messages.success(
            request, f"Support ticket {ticket.ticket_number} was created."
        )
        return redirect(
            "marketplace:support_ticket_detail",
            ticket_number=ticket.ticket_number,
        )
    return render(
        request,
        "marketplace/support_ticket_form.html",
        {
            "form": form,
            "related_listing": listing,
            "related_conversation": conversation,
            "related_reservation": reservation,
        },
    )


@login_required
def support_ticket_detail(request, ticket_number):
    ticket = get_object_or_404(
        SupportTicket.objects.select_related("user", "assigned_to"),
        ticket_number=ticket_number,
        user=request.user,
    )
    form = SupportReplyForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not ticket.customer_can_reply:
            messages.error(
                request,
                "This ticket can no longer be replied to. Please create a new ticket.",
            )
        elif form.is_valid():
            with transaction.atomic():
                ticket = SupportTicket.objects.select_for_update().get(pk=ticket.pk)
                if not ticket.customer_can_reply:
                    messages.error(request, "This ticket can no longer be replied to.")
                    return redirect(
                        "marketplace:support_ticket_detail",
                        ticket_number=ticket.ticket_number,
                    )
                reply = form.save(commit=False)
                reply.ticket = ticket
                reply.sender = request.user
                reply.full_clean()
                reply.save()
                save_support_attachment(reply, form.cleaned_data.get("attachment"))
                if ticket.status in {
                    SupportTicket.RESOLVED,
                    SupportTicket.WAITING_CUSTOMER,
                }:
                    ticket.status = SupportTicket.OPEN
                    ticket.resolved_at = None
                ticket.save(update_fields=["status", "resolved_at", "updated_at"])
            notify_support_reply(ticket, reply)
            messages.success(request, "Your reply was added.")
            return redirect(
                "marketplace:support_ticket_detail",
                ticket_number=ticket.ticket_number,
            )
    return render(
        request,
        "marketplace/support_ticket_detail.html",
        {
            "ticket": ticket,
            "ticket_messages": ticket.messages.select_related("sender").prefetch_related(
                "attachments"
            ),
            "reply_form": form,
            "admin_view": False,
            "base_template": "marketplace/buyer_base.html",
        },
    )


@login_required
def support_attachment_download(request, pk):
    attachment = get_object_or_404(
        SupportAttachment.objects.select_related("message__ticket"),
        pk=pk,
    )
    ticket = attachment.message.ticket
    if request.user.pk != ticket.user_id and not (
        request.user.is_staff or request.user.is_superuser
    ):
        raise PermissionDenied("You do not have access to this attachment.")
    response = FileResponse(
        attachment.file.open("rb"),
        as_attachment=attachment.content_type == "application/pdf",
        content_type=attachment.content_type,
        filename=attachment.original_name,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    return response


@staff_required
def admin_support_tickets(request):
    tickets = SupportTicket.objects.select_related("user", "assigned_to")
    query = request.GET.get("q", "").strip()
    if query:
        tickets = tickets.filter(
            Q(ticket_number__icontains=query)
            | Q(subject__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__email__icontains=query)
        )
    for parameter, lookup, choices in (
        ("status", "status", SupportTicket.STATUS_CHOICES),
        ("category", "category", SupportTicket.CATEGORY_CHOICES),
        ("priority", "priority", SupportTicket.PRIORITY_CHOICES),
    ):
        value = request.GET.get(parameter, "").strip()
        if value in {choice[0] for choice in choices}:
            tickets = tickets.filter(**{lookup: value})
    user_query = request.GET.get("user", "").strip()
    if user_query:
        tickets = tickets.filter(
            Q(user__first_name__icontains=user_query)
            | Q(user__last_name__icontains=user_query)
            | Q(user__email__icontains=user_query)
        )
    for field_name, lookup in (
        ("created_from", "created_at__date__gte"),
        ("created_to", "created_at__date__lte"),
    ):
        value = request.GET.get(field_name, "").strip()
        if value:
            try:
                timezone.datetime.fromisoformat(value)
            except ValueError:
                messages.error(request, "Use a valid ticket date.")
            else:
                tickets = tickets.filter(**{lookup: value})
    paginator = Paginator(tickets, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "marketplace/admin_support_tickets.html",
        {
            "tickets": page_obj.object_list,
            "page_obj": page_obj,
            "status_choices": SupportTicket.STATUS_CHOICES,
            "category_choices": SupportTicket.CATEGORY_CHOICES,
            "priority_choices": SupportTicket.PRIORITY_CHOICES,
        },
    )


@staff_required
def admin_support_ticket_detail(request, ticket_number):
    ticket = get_object_or_404(
        SupportTicket.objects.select_related(
            "user", "assigned_to", "related_listing__goat",
            "related_conversation", "related_reservation",
        ),
        ticket_number=ticket_number,
    )
    reply_form = SupportReplyForm(request.POST or None, request.FILES or None)
    update_form = SupportAdminUpdateForm(instance=ticket)
    if request.method == "POST":
        action = request.POST.get("form_action")
        if action == "reply":
            if ticket.status == SupportTicket.CLOSED:
                messages.error(request, "Closed tickets cannot receive more replies.")
            elif reply_form.is_valid():
                with transaction.atomic():
                    locked = SupportTicket.objects.select_for_update().get(pk=ticket.pk)
                    reply = reply_form.save(commit=False)
                    reply.ticket = locked
                    reply.sender = request.user
                    reply.full_clean()
                    reply.save()
                    save_support_attachment(
                        reply, reply_form.cleaned_data.get("attachment")
                    )
                    if not locked.assigned_to_id:
                        locked.assigned_to = request.user
                        locked.save(update_fields=["assigned_to", "updated_at"])
                notify_support_reply(locked, reply)
                messages.success(request, "Support reply sent.")
                return redirect(
                    "marketplace:admin_support_ticket_detail",
                    ticket_number=ticket.ticket_number,
                )
        elif action == "update":
            previous_status = ticket.status
            update_form = SupportAdminUpdateForm(request.POST, instance=ticket)
            if update_form.is_valid():
                target_status = update_form.cleaned_data["status"]
                allowed = {
                    SupportTicket.OPEN: {
                        SupportTicket.IN_PROGRESS,
                        SupportTicket.RESOLVED,
                        SupportTicket.CLOSED,
                    },
                    SupportTicket.IN_PROGRESS: {
                        SupportTicket.OPEN,
                        SupportTicket.WAITING_CUSTOMER,
                        SupportTicket.RESOLVED,
                        SupportTicket.CLOSED,
                    },
                    SupportTicket.WAITING_CUSTOMER: {
                        SupportTicket.IN_PROGRESS,
                        SupportTicket.RESOLVED,
                        SupportTicket.CLOSED,
                    },
                    SupportTicket.RESOLVED: {
                        SupportTicket.IN_PROGRESS,
                        SupportTicket.CLOSED,
                    },
                    SupportTicket.CLOSED: set(),
                }
                if target_status != previous_status and target_status not in allowed[previous_status]:
                    update_form.add_error("status", "That ticket status change is not allowed.")
                else:
                    updated = update_form.save(commit=False)
                    updated.assigned_to = updated.assigned_to or request.user
                    if target_status == SupportTicket.RESOLVED and previous_status != target_status:
                        updated.resolved_at = timezone.now()
                    elif target_status != SupportTicket.RESOLVED:
                        updated.resolved_at = None
                    if target_status == SupportTicket.CLOSED and previous_status != target_status:
                        updated.closed_at = timezone.now()
                    updated.save()
                    if target_status != previous_status:
                        notify_ticket_status_changed(updated, request.user, previous_status)
                    messages.success(request, "Ticket status and priority updated.")
                    return redirect(
                        "marketplace:admin_support_ticket_detail",
                        ticket_number=ticket.ticket_number,
                    )
        else:
            messages.error(request, "Unknown support ticket action.")
    return render(
        request,
        "marketplace/support_ticket_detail.html",
        {
            "ticket": ticket,
            "ticket_messages": ticket.messages.select_related("sender").prefetch_related(
                "attachments"
            ),
            "reply_form": reply_form,
            "update_form": update_form,
            "admin_view": True,
            "base_template": "base_modern.html",
        },
    )
