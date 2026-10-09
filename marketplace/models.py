import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator, RegexValidator
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.deconstruct import deconstructible


def validate_profile_upload_size(upload):
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError("Profile images must be 5 MB or smaller.")


def validate_supporting_document_size(upload):
    if upload.size > 10 * 1024 * 1024:
        raise ValidationError("Supporting documents must be 10 MB or smaller.")


def validate_support_attachment_size(upload):
    if upload.size > 8 * 1024 * 1024:
        raise ValidationError("Support attachments must be 8 MB or smaller.")


def validate_inquiry_image_size(upload):
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError("Image is too large. Please select a smaller image.")


@deconstructible
class PrivateSupportStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(
            location=settings.PRIVATE_SUPPORT_ROOT,
            base_url=None,
        )


support_attachment_storage = PrivateSupportStorage()


@deconstructible
class PrivateInquiryStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(
            location=settings.PRIVATE_INQUIRY_ROOT,
            base_url=None,
        )


inquiry_image_storage = PrivateInquiryStorage()


def support_attachment_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    ticket_id = instance.message.ticket_id or "pending"
    return f"ticket-{ticket_id}/{uuid.uuid4().hex}{extension}"


def inquiry_image_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    conversation_id = instance.conversation_id or "pending"
    return (
        f"conversation-{conversation_id}/{timezone.now():%Y/%m}/"
        f"{uuid.uuid4().hex}{extension}"
    )


class SellerProfile(models.Model):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    STATUS_CHOICES = [
        (PENDING, "Pending review"),
        (APPROVED, "Approved Seller"),
        (REJECTED, "Declined"),
        (SUSPENDED, "Suspended"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="seller_profile",
    )
    farm_name = models.CharField(max_length=150)
    barangay = models.CharField(max_length=100, blank=True)
    municipality = models.CharField(max_length=100, db_index=True)
    province = models.CharField(max_length=100, db_index=True)
    contact_number = models.CharField(
        max_length=24,
        validators=[
            RegexValidator(
                regex=r"^\+?[0-9][0-9 -]{7,22}$",
                message="Enter a valid contact number using digits, spaces, or hyphens.",
            )
        ],
    )
    profile_image = models.ImageField(
        upload_to="seller_profiles/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
            validate_profile_upload_size,
        ],
    )
    farm_description = models.TextField(max_length=2000)
    address_details = models.TextField(
        blank=True,
        help_text="Private pickup/address details. Never displayed on the public profile.",
    )
    supporting_document = models.FileField(
        upload_to="seller_documents/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png"]),
            validate_supporting_document_size,
        ],
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True
    )
    review_reason = models.TextField(blank=True)
    applied_at = models.DateTimeField(default=timezone.now, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_seller_profiles",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-applied_at"]
        indexes = [
            models.Index(fields=["status", "applied_at"], name="seller_status_applied_idx"),
            models.Index(fields=["province", "municipality"], name="seller_location_idx"),
        ]

    def __str__(self):
        return f"{self.farm_name} ({self.get_status_display()})"

    @property
    def public_location(self):
        return ", ".join(
            part for part in (self.barangay, self.municipality, self.province) if part
        )

    @property
    def is_approved(self):
        return self.status == self.APPROVED


class MarketplaceListing(models.Model):
    DRAFT = "draft"
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"
    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (AVAILABLE, "Available"),
        (RESERVED, "Reserved"),
        (SOLD, "Sold"),
    ]

    # A goat remains the inventory asset. This model stores commercial data only.
    goat = models.OneToOneField(
        "iot.Goat", on_delete=models.PROTECT, related_name="marketplace_listing"
    )
    price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    sales_description = models.TextField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=DRAFT, db_index=True
    )
    is_featured = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Preferred homepage feature; displayed while this listing is available.",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="marketplace_listings",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    sold_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-published_at"], name="listing_status_date_idx"),
            models.Index(fields=["status", "price"], name="listing_status_price_idx"),
            models.Index(fields=["seller", "status"], name="listing_seller_status_idx"),
        ]

    def __str__(self):
        return f"{self.goat.goat_id} - PHP {self.price} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if self.goat_id and self.seller_id:
            if self.goat.owner_id and self.goat.owner_id != self.seller_id:
                from .auth import can_manage_farm

                shared_farm_goat = (
                    self.goat.record_source == "smart_farm"
                    and can_manage_farm(self.seller)
                )
                if not shared_farm_goat:
                    raise ValidationError(
                        {"goat": "A seller can only list a goat belonging to their account."}
                    )
            if self.goat.record_source == "community" and not self.goat.owner_id:
                raise ValidationError({"goat": "Community goats require an owner."})
        if self.status in {self.AVAILABLE, self.RESERVED} and self.seller_id:
            profile = getattr(self.seller, "seller_profile", None)
            from .auth import can_manage_farm
            if not can_manage_farm(self.seller) and not (
                profile and profile.status == SellerProfile.APPROVED
            ):
                raise ValidationError(
                    {"status": "Only approved sellers can publish marketplace listings."}
                )
        if self.goat_id and self.status in {self.DRAFT, self.AVAILABLE, self.RESERVED}:
            if self.goat.status != "active" or not self.goat.is_active:
                raise ValidationError(
                    {"goat": "Only active inventory goats can have an unsold listing."}
                )

    @property
    def can_inquire(self):
        return self.status == self.AVAILABLE and self.goat.status == "active" and self.goat.is_active

    @property
    def can_reserve(self):
        return self.can_inquire


class Conversation(models.Model):
    OPEN = "open"
    CLOSED = "closed"
    STATUS_CHOICES = [
        (OPEN, "Open"),
        (CLOSED, "Closed"),
    ]

    listing = models.ForeignKey(
        MarketplaceListing, on_delete=models.PROTECT, related_name="conversations"
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="marketplace_conversations",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=OPEN, db_index=True
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_marketplace_conversations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["listing", "buyer"], name="uniq_listing_buyer_conversation"
            )
        ]
        indexes = [
            models.Index(
                fields=["buyer", "status", "-updated_at"],
                name="conversation_buyer_idx",
            ),
            models.Index(
                fields=["listing", "status", "-updated_at"],
                name="conversation_listing_idx",
            ),
        ]

    def __str__(self):
        return f"{self.listing.goat.goat_id} / {self.buyer.username}"

    def clean(self):
        super().clean()
        if self.listing_id and self.buyer_id and self.listing.seller_id == self.buyer_id:
            raise ValidationError({"buyer": "A seller cannot inquire about their own listing."})

    def user_is_participant(self, user):
        if not getattr(user, "is_authenticated", False):
            return False
        if user.id == self.buyer_id:
            return True

        # Import locally to avoid a models/scopes import cycle. Farm managers
        # share operational responsibility for smart-farm listings, even when
        # another manager originally created the listing.
        from .scopes import can_manage_listing

        return can_manage_listing(user, self.listing)


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="marketplace_messages",
    )
    body = models.TextField(max_length=2000, blank=True)
    image_attachment = models.ImageField(
        storage=inquiry_image_storage,
        upload_to=inquiry_image_path,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
            validate_inquiry_image_size,
        ],
        blank=True,
    )
    image_original_name = models.CharField(max_length=255, blank=True)
    image_content_type = models.CharField(max_length=100, blank=True)
    image_size = models.PositiveIntegerField(null=True, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["conversation", "is_read", "created_at"],
                name="message_unread_idx",
            )
        ]

    def __str__(self):
        return f"Message from {self.sender} at {self.created_at:%Y-%m-%d %H:%M}"

    def clean(self):
        super().clean()
        if not (self.body and self.body.strip()) and not self.image_attachment:
            raise ValidationError({"body": "Enter a message or attach an image."})
        if self.conversation_id and self.sender_id:
            if not self.conversation.user_is_participant(self.sender):
                raise ValidationError(
                    {"sender": "Only the buyer or an authorized listing manager can send messages."}
                )
            if self.conversation.status != Conversation.OPEN:
                raise ValidationError({"conversation": "This conversation is closed."})


@receiver(post_delete, sender=Message)
def delete_message_image(sender, instance, **kwargs):
    """Remove a private image after its sole owning message is deleted."""
    if instance.image_attachment:
        instance.image_attachment.delete(save=False)


class Reservation(models.Model):
    PENDING = "pending"
    ACCEPTED = "accepted"
    # Compatibility alias for older code while the workflow moves from immediate
    # reservation to seller acceptance.
    RESERVED = ACCEPTED
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    EXPIRED = "expired"
    STATUS_CHOICES = [
        (PENDING, "Pending seller response"),
        (ACCEPTED, "Accepted / Reserved"),
        (REJECTED, "Rejected"),
        (CANCELLED, "Cancelled"),
        (COMPLETED, "Completed"),
        (EXPIRED, "Expired"),
    ]
    NO_PICKUP = "not_requested"
    PICKUP_REQUESTED = "requested"
    PICKUP_SUGGESTED = "suggested"
    PICKUP_CONFIRMED = "confirmed"
    PICKUP_STATUS_CHOICES = [
        (NO_PICKUP, "Not requested"),
        (PICKUP_REQUESTED, "Requested by buyer"),
        (PICKUP_SUGGESTED, "Alternative suggested by seller"),
        (PICKUP_CONFIRMED, "Confirmed"),
    ]

    listing = models.ForeignKey(
        MarketplaceListing, on_delete=models.PROTECT, related_name="reservations"
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="marketplace_reservations",
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name="reservations"
    )
    agreed_price = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True
    )
    reserved_at = models.DateTimeField(default=timezone.now, db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_marketplace_reservations",
    )
    rejection_reason = models.TextField(blank=True)
    pickup_datetime = models.DateTimeField(null=True, blank=True)
    pickup_status = models.CharField(
        max_length=20, choices=PICKUP_STATUS_CHOICES, default=NO_PICKUP
    )
    pickup_notes = models.TextField(blank=True)
    pickup_location = models.CharField(
        max_length=500,
        blank=True,
        help_text="Private pickup location shown only to transaction participants.",
    )
    pickup_proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposed_marketplace_pickups",
    )
    pickup_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_marketplace_pickups",
    )
    pickup_confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_marketplace_sales",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_marketplace_reservations",
    )
    cancellation_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-reserved_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(agreed_price__gte=0),
                name="reservation_price_nonnegative",
            )
        ]
        indexes = [
            models.Index(
                fields=["buyer", "status", "-reserved_at"],
                name="reservation_buyer_idx",
            ),
            models.Index(
                fields=["listing", "status", "-reserved_at"],
                name="reservation_listing_idx",
            ),
            models.Index(
                fields=["status", "expires_at"],
                name="reservation_expiry_idx",
            ),
        ]

    def __str__(self):
        return f"{self.listing.goat.goat_id} reserved by {self.buyer.username}"

    def clean(self):
        super().clean()
        if self.listing_id and self.buyer_id and self.listing.seller_id == self.buyer_id:
            raise ValidationError({"buyer": "A buyer cannot reserve their own listing."})
        if self.conversation_id:
            if self.listing_id and self.conversation.listing_id != self.listing_id:
                raise ValidationError(
                    {"conversation": "The conversation must belong to this listing."}
                )
            if self.buyer_id and self.conversation.buyer_id != self.buyer_id:
                raise ValidationError(
                    {"conversation": "The conversation must belong to this buyer."}
                )
        if self.status in {self.ACCEPTED, self.COMPLETED} and not self.accepted_at:
            raise ValidationError({"accepted_at": "Accepted reservations require a timestamp."})
        if self.expires_at and self.accepted_at and self.expires_at <= self.accepted_at:
            raise ValidationError({"expires_at": "Expiration must be after acceptance."})

    @property
    def is_active(self):
        return self.status in {self.PENDING, self.ACCEPTED}


class MarketplaceActivity(models.Model):
    listing = models.ForeignKey(
        MarketplaceListing, on_delete=models.PROTECT, related_name="activity_logs"
    )
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_activity",
    )
    action = models.CharField(max_length=50, db_index=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Marketplace activities"

    def __str__(self):
        return f"{self.action}: {self.listing.goat.goat_id}"


class Favorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="marketplace_favorites",
    )
    listing = models.ForeignKey(
        MarketplaceListing,
        on_delete=models.CASCADE,
        related_name="favorites",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "listing"],
                name="uniq_marketplace_favorite",
            )
        ]
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="favorite_user_date_idx",
            )
        ]

    def __str__(self):
        return f"{self.user.username} saved {self.listing}"


class MarketplaceReport(models.Model):
    SUSPICIOUS = "suspicious"
    INCORRECT = "incorrect"
    UNAVAILABLE = "unavailable"
    INAPPROPRIATE = "inappropriate"
    SCAM = "scam"
    DUPLICATE = "duplicate"
    OTHER = "other"
    REASON_CHOICES = [
        (SUSPICIOUS, "Suspicious listing"),
        (INCORRECT, "Incorrect information"),
        (UNAVAILABLE, "Goat no longer available"),
        (INAPPROPRIATE, "Inappropriate content"),
        (SCAM, "Possible scam"),
        (DUPLICATE, "Duplicate listing"),
        (OTHER, "Other"),
    ]
    PENDING = "pending"
    REVIEWING = "reviewing"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    STATUS_CHOICES = [
        (PENDING, "Pending review"),
        (REVIEWING, "Under review"),
        (RESOLVED, "Resolved"),
        (DISMISSED, "Dismissed"),
    ]

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="marketplace_reports",
    )
    listing = models.ForeignKey(
        MarketplaceListing,
        on_delete=models.PROTECT,
        related_name="reports",
    )
    reason = models.CharField(max_length=24, choices=REASON_CHOICES)
    description = models.TextField(max_length=2000, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_marketplace_reports",
    )
    resolution_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["reporter", "listing"],
                name="uniq_reporter_listing_report",
            )
        ]
        indexes = [
            models.Index(
                fields=["status", "-created_at"],
                name="report_status_date_idx",
            ),
            models.Index(
                fields=["listing", "status"],
                name="report_listing_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_reason_display()}: {self.listing}"


class MarketplaceNotification(models.Model):
    INQUIRY = "inquiry"
    MESSAGE = "message"
    RESERVATION = "reservation"
    PICKUP = "pickup"
    SALE = "sale"
    SELLER_REVIEW = "seller_review"
    REPORT = "report"
    LISTING = "listing"
    SUPPORT = "support"
    TYPE_CHOICES = [
        (INQUIRY, "Inquiry"),
        (MESSAGE, "Message"),
        (RESERVATION, "Reservation"),
        (PICKUP, "Pickup"),
        (SALE, "Sale"),
        (SELLER_REVIEW, "Seller review"),
        (REPORT, "Listing report"),
        (LISTING, "Listing"),
        (SUPPORT, "Customer support"),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="marketplace_notifications",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_marketplace_notifications",
    )
    notification_type = models.CharField(
        max_length=24,
        choices=TYPE_CHOICES,
        db_index=True,
    )
    title = models.CharField(max_length=180)
    message = models.TextField(max_length=1000, blank=True)
    listing = models.ForeignKey(
        MarketplaceListing,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    report = models.ForeignKey(
        MarketplaceReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    support_ticket = models.ForeignKey(
        "SupportTicket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    dedup_key = models.CharField(max_length=180, unique=True, null=True, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "is_read", "-created_at"],
                name="marketnotif_recipient_idx",
            ),
            models.Index(
                fields=["recipient", "notification_type", "-created_at"],
                name="marketnotif_type_idx",
            ),
        ]

    def __str__(self):
        return f"{self.recipient.username}: {self.title}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    @property
    def target_url_name(self):
        if self.support_ticket_id:
            return "marketplace:support_ticket_detail"
        if self.conversation_id:
            return "marketplace:conversation"
        if self.reservation_id:
            return "marketplace:buyer_reservations"
        if self.listing_id:
            return "marketplace:detail"
        return "marketplace:notifications"


class UserAccountState(models.Model):
    ACTIVE = "active"
    DEACTIVATED = "deactivated"
    SUSPENDED = "suspended"
    STATUS_CHOICES = [
        (ACTIVE, "Active"),
        (DEACTIVATED, "Deactivated"),
        (SUSPENDED, "Suspended"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="marketplace_account_state",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=ACTIVE, db_index=True
    )
    reason = models.TextField(max_length=1000, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="account_state_changes_made",
    )
    changed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user}: {self.get_status_display()}"


class UserActivity(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="important_account_activity",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="important_activity_performed",
    )
    event = models.CharField(max_length=60, db_index=True)
    description = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "User activity"

    def __str__(self):
        return f"{self.user}: {self.event}"

    @property
    def event_label(self):
        return self.event.replace("_", " ").title()


class SupportTicket(models.Model):
    ACCOUNT = "account"
    SELLER_APPLICATION = "seller_application"
    MARKETPLACE = "marketplace"
    RESERVATION = "reservation"
    TECHNICAL = "technical"
    REPORT_USER = "report_user"
    OTHER = "other"
    CATEGORY_CHOICES = [
        (ACCOUNT, "Account Concern"),
        (SELLER_APPLICATION, "Seller Application"),
        (MARKETPLACE, "Marketplace Concern"),
        (RESERVATION, "Reservation / Purchase Concern"),
        (TECHNICAL, "Technical Issue"),
        (REPORT_USER, "Report User / Seller"),
        (OTHER, "Other Concern"),
    ]

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_CUSTOMER = "waiting_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"
    STATUS_CHOICES = [
        (OPEN, "Open"),
        (IN_PROGRESS, "In Progress"),
        (WAITING_CUSTOMER, "Waiting for Customer"),
        (RESOLVED, "Resolved"),
        (CLOSED, "Closed"),
    ]

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    PRIORITY_CHOICES = [
        (LOW, "Low"),
        (NORMAL, "Normal"),
        (HIGH, "High"),
        (URGENT, "Urgent"),
    ]

    ticket_number = models.CharField(
        max_length=20, unique=True, null=True, blank=True, editable=False
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_tickets",
    )
    subject = models.CharField(max_length=180)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, db_index=True)
    description = models.TextField(max_length=5000)
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=OPEN, db_index=True
    )
    priority = models.CharField(
        max_length=12, choices=PRIORITY_CHOICES, default=NORMAL, db_index=True
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_support_tickets",
    )
    related_listing = models.ForeignKey(
        MarketplaceListing,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )
    related_conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )
    related_reservation = models.ForeignKey(
        Reservation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(
                fields=["user", "status", "-updated_at"],
                name="support_user_status_idx",
            ),
            models.Index(
                fields=["status", "priority", "-updated_at"],
                name="support_queue_idx",
            ),
            models.Index(
                fields=["category", "-created_at"],
                name="support_category_idx",
            ),
        ]

    def __str__(self):
        return f"{self.ticket_number or 'Pending ticket'}: {self.subject}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.ticket_number:
            year = timezone.localtime(self.created_at).year
            number = f"SUP-{year}-{self.pk:05d}"
            type(self).objects.filter(
                pk=self.pk, ticket_number__isnull=True
            ).update(ticket_number=number)
            self.ticket_number = number

    @property
    def customer_can_reply(self):
        if self.status in {self.OPEN, self.IN_PROGRESS, self.WAITING_CUSTOMER}:
            return True
        if self.status == self.RESOLVED and self.resolved_at:
            return self.resolved_at >= timezone.now() - timedelta(days=14)
        return False


class SupportMessage(models.Model):
    ticket = models.ForeignKey(
        SupportTicket, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_messages",
    )
    body = models.TextField(max_length=5000)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.ticket.ticket_number}: {self.sender}"

    def clean(self):
        super().clean()
        if not self.body or not self.body.strip():
            raise ValidationError({"body": "Enter a message."})
        if self.ticket_id and self.sender_id:
            if self.sender_id != self.ticket.user_id and not (
                self.sender.is_staff or self.sender.is_superuser
            ):
                raise ValidationError(
                    {"sender": "Only the customer or an administrator can reply."}
                )


class SupportAttachment(models.Model):
    message = models.ForeignKey(
        SupportMessage, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(
        storage=support_attachment_storage,
        upload_to=support_attachment_path,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "pdf"]),
            validate_support_attachment_size,
        ],
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.original_name
