import uuid
import os

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from PIL import Image

from iot.models import Goat
from sms.models import SmsRegistration
from sms.providers import normalize_ph_number

from .image_utils import optimize_marketplace_image
from .auth import is_marketplace_user
from .scopes import manageable_goats
from .models import (
    MarketplaceListing,
    MarketplaceReport,
    Message,
    Reservation,
    SellerProfile,
    SupportMessage,
    SupportTicket,
)


class MarketplaceSignupForm(forms.Form):
    """Additional name fields for allauth's email-first signup form."""
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    sms_phone_number = forms.CharField(
        max_length=20,
        required=False,
        label="Mobile number for SMS (optional)",
        help_text="Philippine mobile number, e.g. 09171234567 or +639171234567.",
        widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
            field.widget.attrs.setdefault(
                "autocomplete", "tel" if name == "sms_phone_number" else "name"
            )

    def clean_sms_phone_number(self):
        number = self.cleaned_data.get("sms_phone_number", "").strip()
        if not number:
            return ""
        try:
            return normalize_ph_number(number)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def signup(self, request, user):
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.save(update_fields=["first_name", "last_name"])
        phone_number = self.cleaned_data.get("sms_phone_number")
        if phone_number:
            SmsRegistration.objects.update_or_create(
                user=user,
                defaults={"phone_number": phone_number, "is_active": True},
            )


class ProfileCompletionForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        kwargs.setdefault(
            "initial",
            {
                "first_name": user.first_name,
                "last_name": user.last_name,
            },
        )
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(
                {
                    "class": "form-control",
                    "autocomplete": "name",
                }
            )

    def save(self):
        self.user.first_name = self.cleaned_data["first_name"].strip()
        self.user.last_name = self.cleaned_data["last_name"].strip()
        self.user.save(update_fields=["first_name", "last_name"])
        return self.user


class SellerApplicationForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)

    class Meta:
        model = SellerProfile
        fields = (
            "first_name",
            "last_name",
            "farm_name",
            "barangay",
            "municipality",
            "province",
            "contact_number",
            "profile_image",
            "farm_description",
            "address_details",
            "supporting_document",
        )
        widgets = {
            "farm_description": forms.Textarea(attrs={"rows": 4}),
            "address_details": forms.Textarea(attrs={"rows": 3}),
            "profile_image": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
            "supporting_document": forms.ClearableFileInput(attrs={"accept": ".pdf,image/jpeg,image/png"}),
        }

    def __init__(self, *args, user, **kwargs):
        self.user = user
        kwargs.setdefault(
            "initial",
            {"first_name": user.first_name, "last_name": user.last_name},
        )
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
            if name in {"first_name", "last_name"}:
                field.widget.attrs.setdefault("autocomplete", "name")
            if name == "contact_number":
                field.widget.attrs.update({"inputmode": "tel", "autocomplete": "tel"})

    def clean(self):
        cleaned_data = super().clean()
        if not is_marketplace_user(self.user):
            raise ValidationError(
                "Administrator and farm-operator accounts cannot apply as community sellers."
            )
        return cleaned_data

    def clean_supporting_document(self):
        upload = self.cleaned_data.get('supporting_document')
        if not upload or not hasattr(upload, 'content_type'):
            return upload

        content_type = (upload.content_type or '').lower()
        signatures = {
            'application/pdf': (b'%PDF-',),
            'image/jpeg': (b'\xff\xd8\xff',),
            'image/png': (b'\x89PNG\r\n\x1a\n',),
        }
        allowed_signatures = signatures.get(content_type)
        if not allowed_signatures:
            raise ValidationError('Upload a valid PDF, JPG, or PNG document.')
        try:
            upload.seek(0)
            header = upload.read(8)
        finally:
            upload.seek(0)
        if not any(header.startswith(signature) for signature in allowed_signatures):
            raise ValidationError('The document content does not match its file type.')
        return upload

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.user = self.user
        self.user.first_name = self.cleaned_data["first_name"].strip()
        self.user.last_name = self.cleaned_data["last_name"].strip()
        if commit:
            self.user.save(update_fields=["first_name", "last_name"])
            profile.save()
        return profile


class ListingForm(forms.ModelForm):
    class Meta:
        model = MarketplaceListing
        fields = ("goat", "price", "sales_description")
        widgets = {
            "price": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "sales_description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, seller=None, **kwargs):
        self.seller = seller
        super().__init__(*args, **kwargs)
        eligible = Goat.all_objects.filter(status="active", is_active=True)
        if seller is not None:
            eligible = manageable_goats(seller, eligible)
        if self.instance.pk:
            eligible = eligible.filter(
                Q(marketplace_listing__isnull=True) | Q(pk=self.instance.goat_id)
            )
        else:
            eligible = eligible.filter(marketplace_listing__isnull=True)
        self.fields["goat"].queryset = eligible.order_by("goat_id")
        for name, field in self.fields.items():
            field.widget.attrs.setdefault(
                "class", "form-select" if name == "goat" else "form-control"
            )


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleImageInput(attrs={"accept": "image/jpeg,image/png,image/webp"})

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        if len(files) > 6:
            raise ValidationError("Upload no more than 6 photos at a time.")
        cleaned = []
        for upload in files:
            image = super().clean(upload, initial)
            if image.size > 5 * 1024 * 1024:
                raise ValidationError("Each goat photo must be 5 MB or smaller.")
            width, height = image.image.size
            if width * height > 25_000_000:
                raise ValidationError("Each goat photo must be 25 megapixels or smaller.")
            try:
                cleaned.append(optimize_marketplace_image(image))
            except (OSError, ValueError):
                raise ValidationError("One of the selected photos could not be processed.")
        return cleaned


class CommunityGoatForm(forms.ModelForm):
    photos = MultipleImageField(required=False, help_text="Upload up to 6 JPG, PNG, or WebP photos.")

    class Meta:
        model = Goat
        fields = (
            "name",
            "tag_number",
            "breed",
            "gender",
            "date_of_birth",
            "weight_kg",
            "color_markings",
            "health_status",
            "health_notes",
            "vaccination_status",
            "vaccine_name",
            "vaccination_date",
            "next_due_date",
            "notes",
        )
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "weight_kg": forms.NumberInput(attrs={"min": "0.1", "max": "300", "step": "0.1", "inputmode": "decimal"}),
            "health_notes": forms.Textarea(attrs={"rows": 3}),
            "vaccination_date": forms.DateInput(attrs={"type": "date"}),
            "next_due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, seller, **kwargs):
        self.seller = seller
        super().__init__(*args, **kwargs)
        self.fields["photos"].required = not bool(self.instance.pk)
        for name, field in self.fields.items():
            if name == "photos":
                field.widget.attrs.setdefault("class", "form-control")
            else:
                field.widget.attrs.setdefault(
                    "class", "form-select" if isinstance(field.widget, forms.Select) else "form-control"
                )

    def clean_date_of_birth(self):
        value = self.cleaned_data.get("date_of_birth")
        if value and value > timezone.localdate():
            raise ValidationError("Date of birth cannot be in the future.")
        return value

    def clean_weight_kg(self):
        value = self.cleaned_data.get("weight_kg")
        if value is not None and not 0.1 <= value <= 300:
            raise ValidationError("Enter a weight from 0.1 to 300 kg.")
        return value

    def save(self, commit=True):
        goat = super().save(commit=False)
        goat.owner = self.seller
        goat.record_source = Goat.COMMUNITY
        if not goat.pk:
            while True:
                candidate = f"CM-{self.seller.pk}-{uuid.uuid4().hex[:8].upper()}"
                if not Goat.all_objects.filter(goat_id=candidate).exists():
                    goat.goat_id = candidate
                    break
            goat.status = "active"
            goat.is_active = True
        if commit:
            goat.full_clean()
            goat.save()
        return goat


class MessageForm(forms.ModelForm):
    # FileField lets the size guard run before Pillow attempts to decode a very
    # large upload. The clean method below still performs full image validation.
    image_attachment = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp",
                "class": "message-image-input",
            }
        ),
    )

    class Meta:
        model = Message
        fields = ("body", "image_attachment")
        widgets = {
            "body": forms.Textarea(attrs={"rows": 3, "maxlength": 2000, "placeholder": "Write a message...", "class": "form-control"}),
        }

    def clean_body(self):
        return self.cleaned_data.get("body", "").strip()

    def clean_image_attachment(self):
        upload = self.cleaned_data.get("image_attachment")
        if not upload:
            return upload
        if upload.size > 5 * 1024 * 1024:
            raise ValidationError("Image is too large. Please select a smaller image.")

        extension = os.path.splitext(upload.name)[1].lower()
        allowed_types = {
            ".jpg": {"image/jpeg"},
            ".jpeg": {"image/jpeg"},
            ".png": {"image/png"},
            ".webp": {"image/webp"},
        }
        content_type = (getattr(upload, "content_type", "") or "").lower()
        if extension not in allowed_types or content_type not in allowed_types[extension]:
            raise ValidationError("Select a valid JPG, PNG, or WebP image.")

        try:
            upload.seek(0)
            image = Image.open(upload)
            image.verify()
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValidationError("Select a valid JPG, PNG, or WebP image.")
            upload.seek(0)
            image = Image.open(upload)
            if image.width * image.height > 25_000_000:
                raise ValidationError("Please select an image smaller than 25 megapixels.")
        except (OSError, ValueError, Image.DecompressionBombError):
            raise ValidationError("The selected image could not be verified.")
        finally:
            upload.seek(0)
        return upload

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("body") and not cleaned_data.get("image_attachment"):
            raise ValidationError("Enter a message or attach an image.")
        return cleaned_data


class MarketplaceReportForm(forms.ModelForm):
    class Meta:
        model = MarketplaceReport
        fields = ("reason", "description")
        widgets = {
            "reason": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "maxlength": 2000,
                    "placeholder": "Briefly explain what the administrator should review.",
                }
            ),
        }

    def clean_description(self):
        return self.cleaned_data.get("description", "").strip()


class PickupRequestForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ("pickup_datetime", "pickup_notes")
        widgets = {
            "pickup_datetime": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "pickup_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pickup_datetime"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["pickup_datetime"].required = True
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_pickup_datetime(self):
        pickup_datetime = self.cleaned_data["pickup_datetime"]
        if pickup_datetime <= timezone.now():
            raise forms.ValidationError("Pickup must be scheduled for a future date and time.")
        return pickup_datetime


class ReservationAcceptanceForm(forms.Form):
    expires_at = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"},
            format="%Y-%m-%dT%H:%M",
        ),
        help_text="Leave blank to use the default 72-hour hold.",
    )
    pickup_location = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "form-control",
                "placeholder": "Private pickup location or meeting point",
            }
        ),
    )

    def clean_expires_at(self):
        value = self.cleaned_data.get("expires_at")
        if value and value <= timezone.now():
            raise forms.ValidationError("Expiration must be in the future.")
        return value


class SellerPickupSuggestionForm(PickupRequestForm):
    pickup_location = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "form-control",
                "placeholder": "Private pickup location or meeting point",
            }
        ),
    )

    class Meta(PickupRequestForm.Meta):
        fields = ("pickup_datetime", "pickup_notes", "pickup_location")


class SupportAttachmentFormMixin(forms.Form):
    attachment = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".jpg,.jpeg,.png,.pdf"}
        ),
        help_text="Optional JPG, PNG, or PDF up to 8 MB.",
    )

    def clean_attachment(self):
        upload = self.cleaned_data.get("attachment")
        if not upload:
            return upload
        if upload.size > 8 * 1024 * 1024:
            raise ValidationError("Attachments must be 8 MB or smaller.")
        extension = os.path.splitext(upload.name)[1].lower()
        allowed_types = {
            ".jpg": {"image/jpeg"},
            ".jpeg": {"image/jpeg"},
            ".png": {"image/png"},
            ".pdf": {"application/pdf"},
        }
        if extension not in allowed_types or upload.content_type not in allowed_types[extension]:
            raise ValidationError("Upload a valid JPG, PNG, or PDF file.")
        try:
            if extension == ".pdf":
                if upload.read(5) != b"%PDF-":
                    raise ValidationError("The selected PDF is not valid.")
            else:
                image = Image.open(upload)
                image.verify()
                if image.format not in {"JPEG", "PNG"}:
                    raise ValidationError("Upload a valid JPG or PNG image.")
        except (OSError, ValueError):
            raise ValidationError("The selected attachment could not be verified.")
        finally:
            upload.seek(0)
        return upload


class SupportTicketForm(SupportAttachmentFormMixin, forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ("subject", "category", "description")
        widgets = {
            "subject": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 180}
            ),
            "category": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 7, "maxlength": 5000}
            ),
        }

    def clean_subject(self):
        return self.cleaned_data["subject"].strip()

    def clean_description(self):
        return self.cleaned_data["description"].strip()


class SupportReplyForm(SupportAttachmentFormMixin, forms.ModelForm):
    class Meta:
        model = SupportMessage
        fields = ("body",)
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "maxlength": 5000,
                    "placeholder": "Write a reply...",
                }
            )
        }

    def clean_body(self):
        return self.cleaned_data["body"].strip()


class SupportAdminUpdateForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ("status", "priority")
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
        }
