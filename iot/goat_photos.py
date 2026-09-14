"""Validation and storage helpers for standardized goat reference photos."""

import base64
import binascii
import json
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from marketplace.image_utils import optimize_marketplace_image

from .goat_models import GoatImage


MAX_GOAT_IMAGE_BYTES = 5 * 1024 * 1024
MAX_GOAT_IMAGE_PIXELS = 25_000_000
MIN_GOAT_IMAGE_WIDTH = 480
MIN_GOAT_IMAGE_HEIGHT = 360
MIN_MEAN_BRIGHTNESS = 24
MAX_MEAN_BRIGHTNESS = 235
MIN_EDGE_VARIANCE = 4.0

ANGLE_GUIDANCE = {
    GoatImage.FRONT: 'Position the goat facing directly toward the camera.',
    GoatImage.LEFT: 'Photograph the complete left side of the goat.',
    GoatImage.RIGHT: 'Photograph the complete right side of the goat.',
    GoatImage.REAR: 'Photograph the goat from directly behind.',
    GoatImage.FACE: (
        "Capture the goat's face clearly, including markings, horn shape, and ears."
    ),
}


def photo_slots(images=(), errors=None):
    """Return template-ready standard angle slots while preserving legacy photos."""
    by_angle = {photo.angle: photo for photo in images if photo.angle}
    errors = errors or {}
    return [
        {
            'angle': value,
            'label': label,
            'guidance': ANGLE_GUIDANCE[value],
            'optional': value == GoatImage.FACE,
            'photo': by_angle.get(value),
            'error': errors.get(value),
        }
        for value, label in GoatImage.ANGLE_CHOICES
    ]


def _check_photo_quality(source):
    source.seek(0)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        width, height = image.size
        if width * height > MAX_GOAT_IMAGE_PIXELS:
            raise ValidationError('Goat photos must be 25 megapixels or smaller.')
        if min(width, height) < MIN_GOAT_IMAGE_HEIGHT or max(width, height) < MIN_GOAT_IMAGE_WIDTH:
            raise ValidationError(
                'Photo resolution is too low. Use an image at least 480 × 360 pixels.'
            )

        grayscale = image.convert('L')
        grayscale.thumbnail((320, 320), Image.Resampling.LANCZOS)
        brightness = ImageStat.Stat(grayscale).mean[0]
        if brightness < MIN_MEAN_BRIGHTNESS:
            raise ValidationError('This photo is too dark. Retake it in better light.')
        if brightness > MAX_MEAN_BRIGHTNESS:
            raise ValidationError('This photo is too bright. Retake it away from glare.')

        edges = grayscale.filter(ImageFilter.FIND_EDGES)
        if edges.width > 4 and edges.height > 4:
            edges = edges.crop((2, 2, edges.width - 2, edges.height - 2))
        if ImageStat.Stat(edges).var[0] < MIN_EDGE_VARIANCE:
            raise ValidationError('This photo appears extremely blurry. Please retake it.')


def validated_goat_image(upload, *, check_quality=False):
    """Verify and normalize an uploaded image before it reaches media storage."""
    if not upload or getattr(upload, 'size', 0) > MAX_GOAT_IMAGE_BYTES:
        raise ValidationError('Goat photos must be 5 MB or smaller.')
    content_type = (getattr(upload, 'content_type', '') or '').lower()
    if content_type not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise ValidationError('Upload a valid JPG, PNG, or WebP image.')
    try:
        upload.seek(0)
        with Image.open(upload) as candidate:
            width, height = candidate.size
            if width * height > MAX_GOAT_IMAGE_PIXELS:
                raise ValidationError('Goat photos must be 25 megapixels or smaller.')
            candidate.verify()
        if check_quality:
            _check_photo_quality(upload)
        upload.seek(0)
        return optimize_marketplace_image(upload)
    except ValidationError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise ValidationError('The selected goat photo could not be verified.') from exc
    finally:
        try:
            upload.seek(0)
        except (AttributeError, OSError):
            pass


def captured_data_url_to_image(data_url, angle):
    """Decode and validate one browser camera capture for a standard angle."""
    if angle not in dict(GoatImage.ANGLE_CHOICES):
        raise ValidationError('Choose a valid goat photo angle.')
    if not isinstance(data_url, str) or ';base64,' not in data_url:
        raise ValidationError('The captured photo data is invalid. Please retake it.')
    header, encoded = data_url.split(';base64,', 1)
    media_type = header.removeprefix('data:').lower()
    extensions = {
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'image/webp': 'webp',
    }
    if media_type not in extensions:
        raise ValidationError('Captured photos must be JPG, PNG, or WebP images.')
    try:
        image_data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValidationError('The captured photo data is invalid. Please retake it.') from exc
    upload = ContentFile(
        image_data,
        name=f'{angle}_{uuid.uuid4().hex[:10]}.{extensions[media_type]}',
    )
    upload.content_type = media_type
    return validated_goat_image(upload, check_quality=True)


def parsed_captures(raw_value):
    """Parse the camera payload as an angle-to-data-URL mapping."""
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError('Captured photo information is invalid. Please retake it.') from exc
    if not isinstance(payload, dict):
        raise ValidationError('Captured photos must be associated with a standard angle.')
    valid_angles = dict(GoatImage.ANGLE_CHOICES)
    return {
        angle: data_url
        for angle, data_url in payload.items()
        if angle in valid_angles and data_url
    }


def prepared_standard_photos(request):
    """Validate all submitted angle uploads/captures before a goat is changed."""
    try:
        captures = parsed_captures(request.POST.get('captured_photos', '').strip())
    except ValidationError as exc:
        return {}, {'general': exc.messages[0]}
    prepared = {}
    errors = {}
    for angle, label in GoatImage.ANGLE_CHOICES:
        try:
            if captures.get(angle):
                prepared[angle] = captured_data_url_to_image(captures[angle], angle)
            else:
                upload = request.FILES.get(f'photo_{angle}')
                if upload:
                    prepared[angle] = validated_goat_image(upload, check_quality=True)
        except ValidationError as exc:
            errors[angle] = exc.messages[0]
    return prepared, errors


def save_standard_photo(goat, angle, normalized_image, *, description=''):
    """Create or replace one categorized photo without creating angle duplicates."""
    valid_angles = dict(GoatImage.ANGLE_CHOICES)
    if angle not in valid_angles:
        raise ValidationError('Choose a valid goat photo angle.')

    with transaction.atomic():
        existing = GoatImage.objects.select_for_update().filter(
            goat=goat,
            angle=angle,
        ).first()
        had_primary = bool(existing and existing.is_primary)
        if existing is None:
            existing = GoatImage(
                goat=goat,
                angle=angle,
                image_type='face' if angle == GoatImage.FACE else 'identification',
            )
        old_name = existing.image.name if existing.pk and existing.image else ''
        old_storage = existing.image.storage if old_name else None
        existing.image = normalized_image
        existing.description = description or f'{valid_angles[angle]} reference photo'
        existing.captured_at = timezone.now()
        existing.is_processed = False
        existing.detected_features = None
        existing.feature_embedding = None
        existing.embedding_extracted = False
        if had_primary or not GoatImage.objects.filter(goat=goat, is_primary=True).exclude(
            pk=existing.pk
        ).exists():
            existing.is_primary = True
        existing.save()

        if old_name and old_name != existing.image.name:
            transaction.on_commit(
                lambda storage=old_storage, name=old_name: storage.delete(name)
            )
        return existing


def delete_goat_photo(photo):
    """Delete a photo and its file, promoting a safe fallback when necessary."""
    goat = photo.goat
    was_primary = photo.is_primary
    name = photo.image.name if photo.image else ''
    storage = photo.image.storage if name else None
    with transaction.atomic():
        photo.delete()
        if was_primary:
            replacement = GoatImage.preferred_from(GoatImage.objects.filter(goat=goat))
            if replacement:
                GoatImage.objects.filter(pk=replacement.pk).update(is_primary=True)
        if name:
            transaction.on_commit(lambda: storage.delete(name))
