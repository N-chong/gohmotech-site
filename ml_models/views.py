from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes as api_permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.permissions import IsAuthenticated
from marketplace.decorators import farm_access_required, farm_owner_required, staff_required
from marketplace.permissions import FarmRolePermission, IsAdmin, IsFarmOwnerOrAdmin
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from django.contrib.auth import get_user_model
from marketplace.auth import can_manage_farm, get_system_role, has_farm_access
from django.utils import timezone
from django.db import IntegrityError, models
from django.conf import settings
from django.core.files import File
from datetime import timedelta
from types import SimpleNamespace
import numpy as np
import base64
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
from .models import MLModel, Detection
from .serializers import MLModelSerializer, DetectionSerializer
from .ml_utils import get_detector, detect_and_identify_goats
from iot.models import Device, Goat, GoatImage
try:
    from iot.goat_models import IPCamera
except ImportError:
    IPCamera = None
import logging

logger = logging.getLogger(__name__)


def _bounded_hours(request, default=24, maximum=168):
    raw_value = request.query_params.get('hours', default)
    try:
        hours = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ApiValidationError({'hours': 'Enter a whole number of hours.'}) from exc
    if not 1 <= hours <= maximum:
        raise ApiValidationError({'hours': f'Hours must be between 1 and {maximum}.'})
    return hours

# Per-category detector cache (lazy loaded).
# Maps category -> {'key': (model_id, updated_at_ts), 'detector': obj}. Keying on
# the active model's (id, updated_at) lets ANY process (web server and Celery
# worker alike) notice an activation/swap and reload, instead of a per-process
# global that only the activating process ever resets.
_detectors = {}

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}


def _model_storage_has_capacity(file_size):
    """Return whether protected storage has room for a model plus a reserve."""
    storage = MLModel._meta.get_field('model_file').storage
    location = Path(storage.location)
    probe = location
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free_bytes = shutil.disk_usage(probe).free
    except OSError:
        logger.exception("Unable to inspect protected model storage capacity")
        return False
    reserve = getattr(settings, 'MODEL_UPLOAD_FREE_SPACE_RESERVE', 256 * 1024 * 1024)
    return free_bytes >= int(file_size) + int(reserve)


def _delete_stored_model_file(model):
    """Best-effort cleanup when storage succeeded but registration did not."""
    if not model.model_file or not model.model_file.name:
        return
    try:
        model.model_file.storage.delete(model.model_file.name)
    except Exception:
        logger.exception("Could not clean up failed model upload %s", model.model_file.name)


MODEL_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
MODEL_UPLOAD_SESSION_MAX_AGE = timedelta(hours=24)


def _upload_staging_root():
    """Return private, same-filesystem staging storage for chunked uploads."""
    storage = MLModel._meta.get_field('model_file').storage
    root = Path(storage.location) / '.upload_staging'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _upload_session_directory(upload_id):
    """Resolve an opaque UUID without allowing traversal outside staging."""
    canonical = str(uuid.UUID(str(upload_id)))
    return _upload_staging_root() / canonical


def _read_upload_session(upload_id, user):
    directory = _upload_session_directory(upload_id)
    metadata_path = directory / 'session.json'
    try:
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('This upload session is missing or expired.') from exc
    if metadata.get('user_id') != user.pk:
        raise PermissionError('This upload session belongs to another user.')
    return directory, metadata


def _write_upload_session(directory, metadata):
    metadata_path = directory / 'session.json'
    temporary_path = directory / 'session.json.tmp'
    temporary_path.write_text(json.dumps(metadata), encoding='utf-8')
    temporary_path.replace(metadata_path)


def _cleanup_expired_upload_sessions():
    """Best-effort removal of abandoned staging files older than 24 hours."""
    root = _upload_staging_root()
    cutoff = timezone.now().timestamp() - MODEL_UPLOAD_SESSION_MAX_AGE.total_seconds()
    for directory in root.iterdir():
        try:
            if directory.is_dir() and directory.stat().st_mtime < cutoff:
                shutil.rmtree(directory)
        except OSError:
            logger.warning("Could not remove expired model upload session %s", directory)


def _is_within_media_root(path_obj: Path) -> bool:
    """Ensure a target path stays inside MEDIA_ROOT."""
    media_root = Path(settings.MEDIA_ROOT).resolve()
    target = path_obj.resolve()
    return media_root == target or media_root in target.parents


def _resolve_existing_media_file(relative_path: str) -> Path:
    """Resolve and validate a media file path selected from existing files."""
    if not relative_path:
        raise ValueError("No existing media file selected.")

    media_root = Path(settings.MEDIA_ROOT)
    candidate = (media_root / relative_path).resolve()

    if not _is_within_media_root(candidate):
        raise ValueError("Invalid media path.")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError("Selected media file does not exist.")

    return candidate


def _encode_image_to_data_url(image: np.ndarray) -> str:
    """Encode OpenCV image to PNG data URL for front-end preview."""
    success, encoded = cv2.imencode('.png', image)
    if not success:
        return ''
    b64_data = base64.b64encode(encoded.tobytes()).decode('utf-8')
    return f"data:image/png;base64,{b64_data}"


def _detector_metadata(model):
    """Add runtime context without mutating the model's stored metadata."""
    metadata = dict(model.metadata or {})
    metadata.setdefault('category', model.category)
    metadata.setdefault('default_label', model.category)
    return metadata


def _extract_best_video_frame(video_path: str, detector) -> tuple:
    """Sample a handful of frames and return the one with strongest detections."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("Unable to open video file.")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    sample_points = []
    if total_frames > 0:
        sample_size = min(12, total_frames)
        step = max(1, total_frames // sample_size)
        sample_points = list(range(0, total_frames, step))[:sample_size]
    else:
        sample_points = [0, 30, 60, 90, 120]

    best_frame = None
    best_result = {'count': 0, 'detections': [], 'confidence': 0.0}
    best_index = 0

    for frame_index in sample_points:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        result = detector.detect(frame)
        score = (result.get('count', 0), result.get('confidence', 0.0))
        best_score = (best_result.get('count', 0), best_result.get('confidence', 0.0))
        if score > best_score:
            best_frame = frame
            best_result = result
            best_index = frame_index

    cap.release()

    if best_frame is None:
        raise ValueError("Unable to read frames from the selected video.")

    return best_frame, best_result, best_index


def _to_embedding_array(embedding_value):
    """Normalize a stored embedding to a numpy array."""
    if embedding_value is None:
        return None

    try:
        array = np.array(embedding_value, dtype=np.float32)
        if array.size == 0:
            return None
        norm = np.linalg.norm(array)
        if norm == 0:
            return None
        return array / norm
    except Exception:
        return None


def _extract_gallery_embedding(goat_image: GoatImage, feature_extractor):
    """Extract and persist embedding for a goat gallery image when missing."""
    if not goat_image.image:
        return None

    image_path = Path(settings.MEDIA_ROOT) / goat_image.image.name
    if not image_path.exists() or not _is_within_media_root(image_path):
        return None

    frame = cv2.imread(str(image_path))
    if frame is None:
        return None

    embedding = feature_extractor.extract(frame)
    embedding_list = embedding.tolist() if isinstance(embedding, np.ndarray) else embedding

    goat_image.feature_embedding = embedding_list
    goat_image.embedding_extracted = True
    goat_image.save(update_fields=['feature_embedding', 'embedding_extracted'])

    return _to_embedding_array(embedding_list)


def _build_gallery_reference_database(feature_extractor):
    """Build recognition references from goat profile embeddings + gallery images."""
    active_goats = list(
        Goat.objects.filter(status='active')
        .prefetch_related('images')
        .order_by('goat_id')
    )

    references = []
    goat_ids_with_gallery_refs = set()
    goat_ids_with_profile_refs = set()

    for goat in active_goats:
        goat_images = list(goat.images.all().order_by('-uploaded_at'))
        for image_record in goat_images:
            embedding_array = _to_embedding_array(image_record.feature_embedding)
            if embedding_array is None:
                embedding_array = _extract_gallery_embedding(image_record, feature_extractor)

            if embedding_array is None:
                continue

            goat_ids_with_gallery_refs.add(goat.id)
            references.append({
                'goat': goat,
                'embedding': embedding_array,
                'reference_type': 'gallery_image',
                'reference_label': image_record.get_image_type_display(),
                'reference_image_url': image_record.image.url if image_record.image else '',
            })

        profile_embedding = _to_embedding_array(goat.feature_embedding)
        if profile_embedding is not None:
            goat_ids_with_profile_refs.add(goat.id)
            references.append({
                'goat': goat,
                'embedding': profile_embedding,
                'reference_type': 'goat_profile',
                'reference_label': 'Goat Profile Embedding',
                'reference_image_url': '',
            })

    return {
        'entries': references,
        'summary': {
            'registered_goat_count': len(active_goats),
            'goats_with_gallery_embeddings': len(goat_ids_with_gallery_refs),
            'goats_with_profile_embeddings': len(goat_ids_with_profile_refs),
            'total_gallery_embeddings': sum(1 for ref in references if ref['reference_type'] == 'gallery_image'),
            'total_reference_embeddings': len(references),
        }
    }


def _run_test_recognition(image: np.ndarray, detector, match_threshold: float = 0.85) -> dict:
    """Run goat detection and matching against registered goats without auto-registering."""
    from .reid_service import get_reid_service

    detection_result = detector.detect(image)
    detections = detection_result.get('detections', [])
    reid_service = get_reid_service(similarity_threshold=match_threshold)
    reference_db = _build_gallery_reference_database(reid_service.feature_extractor)
    reference_entries = reference_db['entries']

    records = []
    recognized_count = 0
    unknown_count = 0

    for index, detection in enumerate(detections, start=1):
        bbox = detection.get('bbox', {})
        x = max(0, int(bbox.get('x', 0)))
        y = max(0, int(bbox.get('y', 0)))
        w = max(0, int(bbox.get('width', 0)))
        h = max(0, int(bbox.get('height', 0)))

        x2 = min(image.shape[1], x + w)
        y2 = min(image.shape[0], y + h)

        if x2 <= x or y2 <= y:
            unknown_count += 1
            records.append({
                'index': index,
                'goat_name': 'Unknown Goat',
                'goat_id': None,
                'detection_confidence': float(detection.get('confidence', 0.0)),
                'bounding_box': {
                    'x': x,
                    'y': y,
                    'width': max(0, x2 - x),
                    'height': max(0, y2 - y),
                },
                'match_percentage': 0.0,
                'recognition_status': 'unknown',
                'status_label': 'Unknown Goat',
            })
            continue

        crop = image[y:y2, x:x2]
        try:
            embedding = reid_service.feature_extractor.extract(crop)
            best_match = None
            best_similarity = 0.0
            for ref in reference_entries:
                similarity = reid_service.feature_extractor.cosine_similarity(embedding, ref['embedding'])
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = ref

            match = None
            if best_match and best_similarity >= match_threshold:
                match = (best_match, best_similarity)
        except Exception as detection_error:
            logger.error(f"Recognition failed for detection #{index}: {detection_error}")
            match = None

        if match:
            reference_entry, similarity = match
            goat = reference_entry['goat']
            recognized_count += 1
            records.append({
                'index': index,
                'goat_name': goat.name or goat.goat_id,
                'goat_id': goat.goat_id,
                'detection_confidence': float(detection.get('confidence', 0.0)),
                'bounding_box': {
                    'x': x,
                    'y': y,
                    'width': max(0, x2 - x),
                    'height': max(0, y2 - y),
                },
                'match_percentage': float(similarity * 100),
                'recognition_status': 'recognized',
                'status_label': 'Recognized',
                'matched_from_gallery': reference_entry['reference_type'] == 'gallery_image',
                'reference_source': 'Goat Gallery' if reference_entry['reference_type'] == 'gallery_image' else 'Profile Embedding',
                'reference_label': reference_entry['reference_label'],
                'gallery_image_url': reference_entry['reference_image_url'],
            })
        else:
            unknown_count += 1
            records.append({
                'index': index,
                'goat_name': 'Unknown Goat',
                'goat_id': None,
                'detection_confidence': float(detection.get('confidence', 0.0)),
                'bounding_box': {
                    'x': x,
                    'y': y,
                    'width': max(0, x2 - x),
                    'height': max(0, y2 - y),
                },
                'match_percentage': 0.0,
                'recognition_status': 'unknown',
                'status_label': 'Not Recognized',
                'matched_from_gallery': False,
                'reference_source': 'No gallery match',
                'reference_label': '',
                'gallery_image_url': '',
            })

    return {
        'detections': records,
        'detection_count': detection_result.get('count', 0),
        'recognized_count': recognized_count,
        'unknown_count': unknown_count,
        'overall_detection_confidence': float(detection_result.get('confidence', 0.0)),
        'reference_database': reference_db['summary'],
    }


def _draw_recognition_overlay(image: np.ndarray, detections: list) -> np.ndarray:
    """Draw recognition boxes and labels for quick visual verification."""
    output = image.copy()

    for item in detections:
        bbox = item.get('bounding_box', {})
        x = int(bbox.get('x', 0))
        y = int(bbox.get('y', 0))
        w = int(bbox.get('width', 0))
        h = int(bbox.get('height', 0))

        recognized = item.get('recognition_status') == 'recognized'
        color = (46, 204, 113) if recognized else (41, 128, 255)

        cv2.rectangle(output, (x, y), (x + w, y + h), color, 3)
        label = f"{item.get('status_label')} | {item.get('match_percentage', 0.0):.1f}%"
        text_y = y - 12 if y - 12 > 20 else y + 24
        cv2.putText(output, label, (x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    return output


def get_active_detector(category='goat'):
    """
    Return the loaded detector for the active model in ``category``.

    The heavy YOLO/Roboflow object is cached per category, but the cache key is
    the active model's ``(id, updated_at)`` — so activating, deactivating, or
    swapping a model is picked up automatically by *any* process (the web server
    and Celery workers alike), instead of a per-process global that only the
    activating process ever reset.

    ``category`` defaults to ``'goat'`` so every existing caller keeps loading
    the goat detector unchanged. Pass ``'person'`` for the person model.
    """
    active_model = (MLModel.objects
                    .filter(category=category, is_active=True)
                    .order_by('-updated_at')
                    .first())
    if not active_model:
        _detectors.pop(category, None)
        return None

    key = (active_model.id, active_model.updated_at.timestamp())
    entry = _detectors.get(category)
    if entry and entry['key'] == key:
        return entry['detector']

    try:
        detector = get_detector(
            model_type=active_model.model_type,
            model_path=active_model.effective_path,
            confidence_threshold=getattr(settings, 'CONFIDENCE_THRESHOLD', 0.5),
            use_gpu=getattr(settings, 'USE_GPU', False),
            metadata=_detector_metadata(active_model)
        )
    except Exception as e:
        logger.error(f"Failed to load {category} detector: {e}")
        return None

    _detectors[category] = {'key': key, 'detector': detector}
    logger.info(f"Loaded active {category} detector: {active_model.name}")
    return detector


def _reset_detector_cache(category=None):
    """Drop the cached detector for one category (or all when ``category`` is None)."""
    if category is None:
        _detectors.clear()
    else:
        _detectors.pop(category, None)


class IsStaffForWrites(IsAuthenticated):
    """
    Reuse the existing auth system for model management authorization:
      * any authenticated user may read (list/retrieve) models;
      * only staff users may upload, activate/deactivate, archive, or delete.

    This satisfies: "Normal users cannot upload models unless permitted. Only
    authorized users can activate/deactivate models." Staff membership is the
    existing permission flag; no separate auth mechanism is introduced.
    """
    WRITE_ACTIONS = {
        'create', 'update', 'partial_update', 'destroy',
        'upload', 'validate_model', 'activate', 'deactivate', 'archive',
    }

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if view.action in self.WRITE_ACTIONS:
            return bool(request.user and request.user.is_staff)
        return True


class MLModelViewSet(viewsets.ModelViewSet):
    """ViewSet for ML Model CRUD + secure upload/validation/activation."""
    queryset = MLModel.objects.all()
    serializer_class = MLModelSerializer
    permission_classes = [IsAdmin]
    filterset_fields = ['category', 'model_type', 'status', 'is_active']

    def perform_destroy(self, instance):
        """
        Do not silently drop model files. We keep the file on disk and instead
        archive the record, unless a superuser explicitly forces deletion.
        (Old models are never auto-deleted.)
        """
        if self.request.query_params.get('force') == 'true' and self.request.user.is_superuser:
            super().perform_destroy(instance)
        else:
            instance.is_active = False
            instance.status = 'archived'
            instance.save(update_fields=['is_active', 'status'])

    @action(detail=False, methods=['post'], url_path='upload-preflight')
    def upload_preflight(self, request):
        """Reject invalid or unsupportable uploads before transferring bytes."""
        from django.core.exceptions import ValidationError
        from .validators import MAX_MODEL_FILE_SIZE, validate_model_upload

        filename = str(request.data.get('filename') or '')
        try:
            file_size = int(request.data.get('size') or 0)
        except (TypeError, ValueError):
            return Response(
                {'error': 'The selected file size is invalid.', 'error_code': 'invalid_file'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_model_upload(SimpleNamespace(name=filename, size=file_size))
        except ValidationError as exc:
            return Response(
                {'error': '; '.join(exc.messages), 'error_code': 'invalid_file'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not _model_storage_has_capacity(file_size):
            return Response(
                {
                    'error': 'Server storage does not have enough free space for this model.',
                    'error_code': 'storage_unavailable',
                },
                status=507,
            )
        return Response({'ready': True, 'file_size': file_size,
                         'max_file_size': MAX_MODEL_FILE_SIZE})

    def _register_uploaded_model(self, uploaded, data, user):
        """Validate, privately store, and register a received model file."""
        from django.core.exceptions import ValidationError
        from .validators import validate_model_upload

        try:
            facts = validate_model_upload(uploaded)
        except ValidationError as exc:
            return Response({'error': '; '.join(exc.messages),
                             'error_code': 'invalid_file'},
                            status=status.HTTP_400_BAD_REQUEST)

        if not _model_storage_has_capacity(facts['size']):
            return Response(
                {
                    'error': 'Server storage does not have enough free space for this model.',
                    'error_code': 'storage_unavailable',
                },
                status=507,
            )

        name = data.get('name')
        version = data.get('version', '1.0')
        if not name:
            return Response({'error': 'Model name is required.', 'error_code': 'invalid_request'},
                            status=status.HTTP_400_BAD_REQUEST)

        category = data.get('category', 'other')
        model_type = data.get('model_type', 'yolov8')

        valid_categories = {value for value, _label in MLModel.CATEGORY_CHOICES}
        valid_model_types = {value for value, _label in MLModel.MODEL_TYPES}
        if category not in valid_categories:
            return Response({'error': 'Unsupported model category.', 'error_code': 'invalid_request'},
                            status=status.HTTP_400_BAD_REQUEST)
        if model_type not in valid_model_types:
            return Response({'error': 'Unsupported model type.', 'error_code': 'invalid_request'},
                            status=status.HTTP_400_BAD_REQUEST)
        if model_type == 'rfdetr' and facts['extension'] not in {'.pt', '.pth', '.ckpt'}:
            return Response(
                {'error': 'RF-DETR uploads must be .pt, .pth, or .ckpt checkpoints.',
                 'error_code': 'invalid_file'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        metadata = None
        if model_type == 'rfdetr':
            rfdetr_variant = data.get('rfdetr_variant', 'nano').lower()
            if rfdetr_variant not in {'auto', 'nano', 'small', 'medium', 'large'}:
                return Response({'error': 'Unsupported RF-DETR model size.',
                                 'error_code': 'invalid_request'},
                                status=status.HTTP_400_BAD_REQUEST)
            metadata = {'rfdetr': {'variant': rfdetr_variant}}

        if MLModel.objects.filter(name=name, version=version).exists():
            return Response(
                {'error': f"A model named '{name}' version '{version}' already exists.",
                 'error_code': 'duplicate_model'},
                status=status.HTTP_400_BAD_REQUEST)

        model = MLModel(
            name=name,
            version=version,
            category=category,
            model_type=model_type,
            description=data.get('description', ''),
            metadata=metadata,
            uploaded_by=user,
            file_size=facts['size'],
            status='uploaded',
            is_active=False,  # never auto-activate
        )
        # Store under the validated basename. Large uploads arrive as
        # TemporaryUploadedFile objects, so FileSystemStorage moves/copies them
        # in chunks rather than reading the entire checkpoint into Python RAM.
        try:
            model.model_file.save(facts['safe_name'], uploaded, save=False)
            storage = model.model_file.storage
            if (
                not storage.exists(model.model_file.name)
                or storage.size(model.model_file.name) != facts['size']
            ):
                raise OSError('Stored model size does not match the received upload.')
            model.save()
        except IntegrityError:
            _delete_stored_model_file(model)
            logger.warning("Duplicate model registration raced with upload: %s v%s", name, version)
            return Response(
                {
                    'error': f"A model named '{name}' version '{version}' already exists.",
                    'error_code': 'duplicate_model',
                },
                status=status.HTTP_409_CONFLICT,
            )
        except OSError:
            _delete_stored_model_file(model)
            logger.exception("Model upload could not be stored or registered")
            return Response(
                {
                    'error': 'The server could not store the uploaded model. '
                             'The existing active model was not changed.',
                    'error_code': 'storage_unavailable',
                },
                status=507,
            )
        except Exception:
            _delete_stored_model_file(model)
            logger.exception("Unexpected error while registering model upload")
            return Response(
                {
                    'error': 'The server could not register the uploaded model. '
                             'The existing active model was not changed.',
                    'error_code': 'server_error',
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        serializer = self.get_serializer(model)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def upload(self, request):
        """
        Securely register a model received in one request.

        This endpoint remains available for API compatibility and smaller
        files. Browser uploads use the chunked endpoints below so requests can
        safely pass through proxies with lower per-request limits.
        """
        uploaded = request.FILES.get('model_file') or request.FILES.get('file')
        if not uploaded:
            return Response({'error': 'Choose a model weights file to upload.',
                             'error_code': 'invalid_file'},
                            status=status.HTTP_400_BAD_REQUEST)
        return self._register_uploaded_model(uploaded, request.data, request.user)

    @action(detail=False, methods=['post'], url_path='upload-session')
    def upload_session(self, request):
        """Create an opaque private staging session for a chunked upload."""
        preflight = self.upload_preflight(request)
        if preflight.status_code != status.HTTP_200_OK:
            return preflight

        from django.core.exceptions import ValidationError
        from .validators import validate_model_upload

        try:
            facts = validate_model_upload(SimpleNamespace(
                name=str(request.data.get('filename') or ''),
                size=int(request.data.get('size') or 0),
            ))
        except (ValidationError, TypeError, ValueError) as exc:
            messages = getattr(exc, 'messages', [str(exc)])
            return Response({'error': '; '.join(messages), 'error_code': 'invalid_file'},
                            status=status.HTTP_400_BAD_REQUEST)

        _cleanup_expired_upload_sessions()
        upload_id = str(uuid.uuid4())
        directory = _upload_session_directory(upload_id)
        directory.mkdir(mode=0o700)
        metadata = {
            'upload_id': upload_id,
            'user_id': request.user.pk,
            'safe_name': facts['safe_name'],
            'size': facts['size'],
            'chunk_size': MODEL_UPLOAD_CHUNK_SIZE,
            'total_chunks': (facts['size'] + MODEL_UPLOAD_CHUNK_SIZE - 1) // MODEL_UPLOAD_CHUNK_SIZE,
            'next_index': 0,
            'received': 0,
            'created_at': timezone.now().isoformat(),
        }
        _write_upload_session(directory, metadata)
        return Response({
            'ready': True,
            'upload_id': upload_id,
            'file_size': facts['size'],
            'chunk_size': MODEL_UPLOAD_CHUNK_SIZE,
            'total_chunks': metadata['total_chunks'],
        })

    @action(detail=False, methods=['post'], url_path='upload-chunk')
    def upload_chunk(self, request):
        """Append one verified, sequential chunk to private staging storage."""
        upload_id = request.data.get('upload_id')
        chunk = request.FILES.get('chunk')
        try:
            chunk_index = int(request.data.get('chunk_index'))
            directory, metadata = _read_upload_session(upload_id, request.user)
        except PermissionError as exc:
            return Response({'error': str(exc), 'error_code': 'forbidden'},
                            status=status.HTTP_403_FORBIDDEN)
        except (TypeError, ValueError) as exc:
            return Response({'error': str(exc) or 'Invalid upload session.',
                             'error_code': 'invalid_session'},
                            status=status.HTTP_400_BAD_REQUEST)

        if not chunk:
            return Response({'error': 'No upload chunk was received.',
                             'error_code': 'invalid_chunk'},
                            status=status.HTTP_400_BAD_REQUEST)
        if chunk_index != metadata['next_index']:
            return Response({
                'error': 'Upload chunks arrived out of order. Retry the upload from the beginning.',
                'error_code': 'invalid_chunk_order',
            }, status=status.HTTP_409_CONFLICT)

        remaining = metadata['size'] - metadata['received']
        expected_size = min(metadata['chunk_size'], remaining)
        if chunk.size != expected_size:
            return Response({
                'error': 'The received upload chunk has an unexpected size.',
                'error_code': 'invalid_chunk',
            }, status=status.HTTP_400_BAD_REQUEST)

        part_path = directory / 'model.part'
        original_size = part_path.stat().st_size if part_path.exists() else 0
        if original_size != metadata['received']:
            return Response({
                'error': 'The staged upload is inconsistent. Retry from the beginning.',
                'error_code': 'invalid_session',
            }, status=status.HTTP_409_CONFLICT)
        try:
            with part_path.open('ab') as destination:
                for piece in chunk.chunks():
                    destination.write(piece)
            metadata['received'] += chunk.size
            metadata['next_index'] += 1
            _write_upload_session(directory, metadata)
        except OSError:
            try:
                with part_path.open('r+b') as destination:
                    destination.truncate(original_size)
            except OSError:
                pass
            logger.exception('Could not store chunk %s for upload %s', chunk_index, upload_id)
            return Response({'error': 'The server could not store this upload chunk.',
                             'error_code': 'storage_unavailable'}, status=507)

        return Response({
            'received': metadata['received'],
            'next_index': metadata['next_index'],
            'complete': metadata['received'] == metadata['size'],
        })

    @action(detail=False, methods=['post'], url_path='complete-upload')
    def complete_upload(self, request):
        """Validate and register a completely assembled staged model."""
        try:
            directory, metadata = _read_upload_session(
                request.data.get('upload_id'), request.user
            )
        except PermissionError as exc:
            return Response({'error': str(exc), 'error_code': 'forbidden'},
                            status=status.HTTP_403_FORBIDDEN)
        except (TypeError, ValueError) as exc:
            return Response({'error': str(exc) or 'Invalid upload session.',
                             'error_code': 'invalid_session'},
                            status=status.HTTP_400_BAD_REQUEST)

        part_path = directory / 'model.part'
        if (
            metadata['received'] != metadata['size']
            or metadata['next_index'] != metadata['total_chunks']
            or not part_path.is_file()
            or part_path.stat().st_size != metadata['size']
        ):
            return Response({
                'error': 'The model upload is incomplete. Retry from the beginning.',
                'error_code': 'incomplete_upload',
            }, status=status.HTTP_409_CONFLICT)

        try:
            with part_path.open('rb') as source:
                uploaded = File(source, name=metadata['safe_name'])
                response = self._register_uploaded_model(uploaded, request.data, request.user)
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        return response

    @action(detail=True, methods=['post'], url_path='validate')
    def validate_model(self, request, pk=None):
        """
        Re-run file checks, load the detector candidate, and mark it validated.
        A model must pass this step before it can be activated.
        """
        from django.core.exceptions import ValidationError
        from .validators import validate_model_upload

        model = self.get_object()
        if not model.model_file:
            return Response({'error': 'This model has no uploaded file to validate.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_model_upload(model.model_file)
        except OSError:
            return Response(
                {'error': 'The stored model file is missing or unavailable. Restore the weights file or upload it again.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValidationError as exc:
            model.status = 'rejected'
            model.validation_notes = '; '.join(exc.messages)
            model.save(update_fields=['status', 'validation_notes'])
            return Response({'error': model.validation_notes},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            get_detector(
                model_type=model.model_type,
                model_path=model.effective_path,
                confidence_threshold=getattr(settings, 'CONFIDENCE_THRESHOLD', 0.5),
                use_gpu=getattr(settings, 'USE_GPU', False),
                metadata=_detector_metadata(model),
            )
        except Exception:
            logger.exception("Uploaded model load validation failed")
            model.status = 'rejected'
            model.validation_notes = (
                'The checkpoint passed file checks but could not be loaded by '
                'the configured detector.'
            )
            model.save(update_fields=['status', 'validation_notes'])
            return Response(
                {'error': model.validation_notes}, status=status.HTTP_400_BAD_REQUEST
            )

        model.status = 'validated'
        model.validation_notes = 'Passed file checks and detector load validation.'
        model.save(update_fields=['status', 'validation_notes'])
        return Response(self.get_serializer(model).data)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """
        Activate this model, deactivating other models of the SAME category.

        Categories are independent: activating a person model no longer turns
        off the active goat model, so goat and person detection can run together
        on the same frame. Refuses to activate a model that has an uploaded file
        but has not been validated (no auto-activation of unvalidated uploads).
        """
        model = self.get_object()

        if model.model_file and model.status not in ('validated', 'active', 'inactive'):
            return Response(
                {'error': 'Model must be validated before activation.'},
                status=status.HTTP_400_BAD_REQUEST)

        # Load every newly uploaded local candidate before changing the active
        # record. A corrupt or incompatible checkpoint must never take the
        # currently working detector offline.
        candidate_detector = None
        if model.model_file:
            try:
                candidate_detector = get_detector(
                    model_type=model.model_type,
                    model_path=model.effective_path,
                    confidence_threshold=getattr(settings, 'CONFIDENCE_THRESHOLD', 0.5),
                    use_gpu=getattr(settings, 'USE_GPU', False),
                    metadata=_detector_metadata(model),
                )
            except Exception:
                logger.exception("Candidate model activation validation failed")
                return Response(
                    {
                        'error': 'The uploaded model could not be loaded. The previous '
                                 'active model remains available.'
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        MLModel.objects.filter(category=model.category, is_active=True)\
            .exclude(pk=model.pk).update(is_active=False, status='inactive')
        model.is_active = True
        model.status = 'active'
        model.save(update_fields=['is_active', 'status', 'updated_at'])

        if candidate_detector is None:
            _reset_detector_cache(model.category)  # force reload for this category
        else:
            key = (model.id, model.updated_at.timestamp())
            _detectors[model.category] = {'key': key, 'detector': candidate_detector}
        return Response({'status': 'Model activated', 'id': model.id})

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate this model without deleting it."""
        model = self.get_object()
        model.is_active = False
        model.status = 'inactive'
        model.save(update_fields=['is_active', 'status', 'updated_at'])
        _reset_detector_cache(model.category)
        return Response({'status': 'Model deactivated', 'id': model.id})

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive an old model (kept on disk, never auto-deleted)."""
        model = self.get_object()
        model.is_active = False
        model.status = 'archived'
        model.save(update_fields=['is_active', 'status'])
        return Response({'status': 'Model archived', 'id': model.id})


class DetectionViewSet(viewsets.ModelViewSet):
    """ViewSet for Detection operations"""
    queryset = Detection.objects.all()
    serializer_class = DetectionSerializer
    permission_classes = [FarmRolePermission]
    filterset_fields = ['camera', 'processed', 'timestamp']
    
    @action(detail=False, methods=['get'])
    def recent(self, request):
        """Get recent detections"""
        hours = _bounded_hours(request)
        since = timezone.now() - timedelta(hours=hours)
        
        try:
            limit = max(1, min(500, int(request.query_params.get('limit', 500))))
        except (TypeError, ValueError):
            limit = 500
        detections = Detection.objects.filter(timestamp__gte=since).order_by('-timestamp')[:limit]
        serializer = self.get_serializer(detections, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get detection statistics"""
        hours = _bounded_hours(request)
        since = timezone.now() - timedelta(hours=hours)
        
        detections = Detection.objects.filter(timestamp__gte=since)
        
        stats = detections.aggregate(
            total_detections=models.Count('id'),
            total_goats=models.Sum('goat_count'),
            average_confidence=models.Avg('confidence'),
            cameras_active=models.Count('camera', distinct=True),
        )
        stats['total_goats'] = stats['total_goats'] or 0
        stats['average_confidence'] = stats['average_confidence'] or 0
        
        return Response(stats)


# Class labels that count as a "person" detection. A dedicated single-class
# person model may name its one class differently, so a 1-class model's every
# box is treated as a person as well (see _extract_persons).
PERSON_LABELS = {'person'}


def _extract_persons(detector, detect_result):
    """Filter a detector's raw result down to person boxes.

    COCO-style models emit many classes, so keep only ``PERSON_LABELS``. A model
    whose ``names`` maps exactly one class is assumed to be a dedicated person
    detector, so every box is kept regardless of the class string.
    """
    names = getattr(getattr(detector, 'model', None), 'names', None)
    single_class = isinstance(names, dict) and len(names) == 1
    return [
        d for d in detect_result.get('detections', [])
        if single_class or str(d.get('label', '')).lower() in PERSON_LABELS
    ]


@api_view(['POST'])
@api_permission_classes([IsFarmOwnerOrAdmin])
def detect_goats_api(request):
    """
    API endpoint for goat detection and identification
    
    POST /api/ml/detect/
    Form data:
        - image: Image file
        - camera_id: Camera device ID (optional)
        - enable_reid: Enable re-identification (default: True)
    """
    if 'image' not in request.FILES:
        return Response(
            {'error': 'No image provided'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        image_file = request.FILES['image']
        camera_id = request.data.get('camera_id')
        enable_reid = request.data.get('enable_reid', 'true').lower() == 'true'
        
        # Read image
        image_bytes = np.frombuffer(image_file.read(), np.uint8)
        image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
        
        if image is None:
            return Response(
                {'error': 'Invalid image format'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get detector
        detector = get_active_detector()
        if not detector:
            return Response(
                {'error': 'No active ML model found'}, 
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        # Resolve the camera to TWO different objects: the IPCamera (used by
        # re-id, the person pipeline, and snapshots) and the iot.Device that
        # Detection.camera actually points at. Resolve by camera_id then id
        # (mirrors iot.ai_tasks.start_realtime_detection); .filter().first()
        # also tolerates a non-numeric camera_id (the id= branch is guarded).
        ip_camera = None
        device = None
        if camera_id and IPCamera:
            ip_camera = IPCamera.objects.filter(camera_id=camera_id).first()
            if ip_camera is None and str(camera_id).isdigit():
                ip_camera = IPCamera.objects.filter(id=camera_id).first()
            if ip_camera is None:
                logger.warning(f"Camera {camera_id} not found")
            else:
                device = Device.objects.filter(
                    device_id=ip_camera.camera_id, device_type='camera'
                ).first()

        # Run detection + identification
        result = detect_and_identify_goats(
            image=image,
            detector=detector,
            camera=ip_camera,
            enable_reid=enable_reid
        )

        # Save to database (basic detection record). Detection.camera is a FK to
        # iot.Device, so it gets `device` (or None) — never the IPCamera. Stamp
        # the row with the active GOAT model (a person model may also be active).
        active_model = MLModel.objects.filter(category='goat', is_active=True).first()
        detection = Detection.objects.create(
            model=active_model,
            camera=device,
            goat_count=result['detection_count'],
            confidence=result['confidence'],
            bounding_boxes=result['detections'],
            processed=True
        )
        
        # Prepare response
        response_data = {
            'id': detection.id,
            'detection_count': result['detection_count'],
            'confidence': result['confidence'],
            'detections': result['detections'],
            'reid_enabled': result['reid_enabled'],
            'timestamp': detection.timestamp.isoformat()
        }
        
        # Add identification results if enabled
        if result['reid_enabled']:
            response_data['identified_goats'] = [
                {
                    'goat_id': g['goat_id'],
                    'similarity': g['similarity'],
                    'bbox': g['bbox'],
                    'is_new': False
                }
                for g in result['identified_goats']
            ]
            response_data['new_goats'] = [
                {
                    'goat_id': g['goat_id'],
                    'bbox': g['bbox'],
                    'is_new': True
                }
                for g in result['new_goats']
            ]
            response_data['identified_count'] = len(result['identified_goats'])
            response_data['new_count'] = len(result['new_goats'])
        
        # --- Person detection (additive) ---
        # Runs only when a person-category model is active. Wrapped in its own
        # try/except so a failure here never breaks the goat response.
        person_detector = get_active_detector('person')
        if person_detector is not None:
            try:
                pres = person_detector.detect(image)          # raw detect, NOT the goat re-id path
                persons = _extract_persons(person_detector, pres)
                thr = getattr(settings, 'PERSON_CONFIDENCE_THRESHOLD', 0.5)
                persons = [p for p in persons if p.get('confidence', 0) >= thr]
                person_block = {
                    'count': len(persons),
                    'detections': persons,
                    'confidence': max((p['confidence'] for p in persons), default=0.0),
                    'detection_id': None,
                    'created': False,
                }
                if persons:
                    # function-local import: ml_models loads before security in
                    # INSTALLED_APPS, so import at call time, not module load.
                    from security.services import record_person_detection
                    ok, jpg = cv2.imencode('.jpg', image)
                    person_det, created = record_person_detection(
                        camera=ip_camera,
                        source_label='' if ip_camera else (
                            f"Live feed ({camera_id})" if camera_id else "Live feed"),
                        confidence=person_block['confidence'],
                        bounding_boxes=persons,
                        snapshot_bytes=(jpg.tobytes() if ok else None),
                        detection_type='person',
                    )
                    person_block['detection_id'] = person_det.id
                    person_block['created'] = created
                response_data['persons'] = person_block
            except Exception:
                logger.error("Person detection path failed", exc_info=True)

        return Response(response_data)
        
    except Exception:
        logger.exception("Detection request failed")
        return Response(
            {'error': 'Detection could not be completed.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@api_permission_classes([IsAdmin])
def test_recognition_api(request):
    """Run recognition testing on uploaded or existing image/video media."""
    if not CV2_AVAILABLE:
        return Response({'error': 'OpenCV is required for test recognition.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    detector = get_active_detector()
    if not detector:
        return Response({'error': 'No active ML model found'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    source_type = request.data.get('source_type', 'upload_image')
    match_threshold = float(request.data.get('match_threshold', 0.85) or 0.85)
    match_threshold = max(0.1, min(0.99, match_threshold))

    temp_video_path = None

    try:
        image = None
        media_type = 'image'
        frame_index = 0

        if source_type == 'upload_image':
            uploaded = request.FILES.get('image')
            if not uploaded:
                return Response({'error': 'Please upload an image file.'}, status=status.HTTP_400_BAD_REQUEST)
            image_bytes = np.frombuffer(uploaded.read(), np.uint8)
            image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
            if image is None:
                return Response({'error': 'Invalid image format.'}, status=status.HTTP_400_BAD_REQUEST)

        elif source_type == 'upload_video':
            uploaded = request.FILES.get('video')
            if not uploaded:
                return Response({'error': 'Please upload a video file.'}, status=status.HTTP_400_BAD_REQUEST)

            suffix = Path(uploaded.name).suffix or '.mp4'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                temp_video_path = tmp_file.name
                for chunk in uploaded.chunks():
                    tmp_file.write(chunk)

            media_type = 'video'
            image, _, frame_index = _extract_best_video_frame(temp_video_path, detector)

        elif source_type == 'existing':
            relative_path = request.data.get('existing_media_path', '').strip()
            file_path = _resolve_existing_media_file(relative_path)
            extension = file_path.suffix.lower()

            if extension in VIDEO_EXTENSIONS:
                media_type = 'video'
                image, _, frame_index = _extract_best_video_frame(str(file_path), detector)
            else:
                media_type = 'image'
                image = cv2.imread(str(file_path))

            if image is None:
                return Response({'error': 'Unable to load selected media file.'}, status=status.HTTP_400_BAD_REQUEST)

        else:
            return Response({'error': 'Invalid source type.'}, status=status.HTTP_400_BAD_REQUEST)

        recognition = _run_test_recognition(image=image, detector=detector, match_threshold=match_threshold)
        detections = recognition['detections']

        if recognition['detection_count'] == 0:
            recognition_status = 'no_detection'
            detection_status = 'No goat detected'
        elif recognition['recognized_count'] == recognition['detection_count']:
            recognition_status = 'recognized'
            detection_status = 'Goat detected'
        elif recognition['recognized_count'] > 0:
            recognition_status = 'partial'
            detection_status = 'Goat detected'
        else:
            recognition_status = 'unknown'
            detection_status = 'Goat detected'

        overlay_image = _draw_recognition_overlay(image, detections)

        return Response({
            'processing_status': 'completed',
            'detection_status': detection_status,
            'recognition_status': recognition_status,
            'error': '',
            'media_type': media_type,
            'frame_index': frame_index,
            'match_threshold': match_threshold,
            'detection_count': recognition['detection_count'],
            'recognized_count': recognition['recognized_count'],
            'unknown_count': recognition['unknown_count'],
            'overall_detection_confidence': recognition['overall_detection_confidence'],
            'reference_database': recognition['reference_database'],
            'detections': detections,
            'source_frame': _encode_image_to_data_url(image),
            'annotated_preview': _encode_image_to_data_url(overlay_image),
        })

    except Exception:
        logger.exception("Test recognition request failed")
        return Response({
            'processing_status': 'failed',
            'detection_status': 'Failed',
            'recognition_status': 'failed',
            'error': 'Recognition could not be completed.',
            'detections': [],
            'source_frame': '',
            'annotated_preview': '',
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if temp_video_path and os.path.exists(temp_video_path):
            os.remove(temp_video_path)


# Django Template Views (HTML Pages)

@staff_required
def test_detection_view(request):
    """Recognition testing page for uploaded/existing image or video media."""
    active_model = MLModel.objects.filter(category='goat', is_active=True).first()

    registered_goat_media = list(
        GoatImage.objects.select_related('goat')
        .filter(goat__status='active')
        .order_by('-uploaded_at')[:120]
    )

    registered_media_options = []
    for img in registered_goat_media:
        if not img.image:
            continue
        label_name = img.goat.name or img.goat.goat_id
        registered_media_options.append({
            'label': f"{img.goat.goat_id} - {label_name} ({img.get_image_type_display()})",
            'path': img.image.name,
            'url': img.image.url,
            'media_type': 'image',
        })

    library_media_options = []
    media_root = Path(settings.MEDIA_ROOT)
    if media_root.exists():
        for file_path in media_root.rglob('*'):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            if ext not in IMAGE_EXTENSIONS and ext not in VIDEO_EXTENSIONS:
                continue
            if not _is_within_media_root(file_path):
                continue

            relative_path = str(file_path.relative_to(media_root)).replace('\\', '/')
            media_type = 'video' if ext in VIDEO_EXTENSIONS else 'image'
            library_media_options.append({
                'label': relative_path,
                'path': relative_path,
                'url': f"{settings.MEDIA_URL}{relative_path}",
                'media_type': media_type,
            })

    library_media_options = library_media_options[:200]
    
    return render(request, 'ml_models/test_detection.html', {
        'active_model': active_model,
        'page_title': 'Test Goat Recognition',
        'registered_media_options': registered_media_options,
        'library_media_options': library_media_options,
    })


@staff_required
def diagnostics_view(request):
    """Diagnostics page for debugging live detection"""
    return render(request, 'ml_models/diagnostics.html', {
        'page_title': 'Detection Diagnostics'
    })


@farm_access_required
def detection_feed_view(request):
    """Live detection feed page - Single camera goat house monitoring"""
    camera = None
    if IPCamera:
        camera = IPCamera.objects.filter(is_active=True).first()
    # Surface the real active model (same pattern as the test page) so the UI
    # can show its name/version instead of a static "AI Detection Active" badge.
    active_model = MLModel.objects.filter(category='goat', is_active=True).first()
    return render(request, 'ml_models/detection_feed.html', {
        'camera': camera,
        'active_model': active_model,
        'page_title': 'Live Detection Feed'
    })


@farm_access_required
@require_http_methods(["GET", "POST"])
def live_detection_control(request):
    """Small control/status API; camera frames never transit this endpoint."""
    from .live_detection import redis_client, key, status as live_status, viewer_heartbeat, viewer_leave

    camera = IPCamera.objects.filter(is_active=True).first()
    if camera is None:
        return JsonResponse({"error": "No active camera"}, status=404)
    client = redis_client()
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            action = body.get("action")
            token = body.get("token", "")
            if action == "view":
                viewer_heartbeat(camera.id, token, client)
            elif action == "leave":
                viewer_leave(camera.id, token, client)
            elif action == "manual_start" and can_manage_farm(request.user):
                viewer_heartbeat(camera.id, token, client)
                client.set(key(camera.id, "manual"), token)
            elif action == "manual_stop" and can_manage_farm(request.user):
                client.delete(key(camera.id, "manual"))
            elif action == "set_interval" and can_manage_farm(request.user):
                interval = int(body.get("interval"))
                if not 2 <= interval <= 60:
                    return JsonResponse({"error": "Interval must be 2 to 60 seconds"}, status=400)
                camera.detection_interval_seconds = interval
                camera.save(update_fields=["detection_interval_seconds"])
            else:
                return JsonResponse({"error": "Invalid action or permission"}, status=403)
        except (ValueError, TypeError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid request"}, status=400)
    return JsonResponse(live_status(camera.id, client))


@farm_access_required
@require_http_methods(["POST"])
def user_presence_control(request):
    """Record a visible, recently used farm page for the signed-in account."""
    from .user_presence import heartbeat, leave

    try:
        body = json.loads(request.body)
        action = body.get("action")
        token = body.get("token", "")
        if action == "view":
            heartbeat(token, request.user.pk)
        elif action == "leave":
            leave(token, request.user.pk)
        else:
            return JsonResponse({"error": "Invalid action"}, status=400)
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid request"}, status=400)
    return JsonResponse({"ok": True})


@staff_required
@never_cache
@require_http_methods(["GET"])
def active_users_view(request):
    """Show admins distinct farm accounts with recent browser presence."""
    from .user_presence import active_accounts

    activity = active_accounts()
    role_labels = {
        "admin": "Administrator",
        "farm_owner": "Farm owner",
        "farm_operator": "Farm operator",
    }
    rows = []
    for user in get_user_model().objects.filter(pk__in=activity, is_active=True):
        if not has_farm_access(user):
            continue
        signal = activity[user.pk]
        rows.append({
            "name": user.get_full_name() or user.get_username(),
            "username": user.get_username(),
            "role": role_labels.get(get_system_role(user), "Farm user"),
            "pages": signal["pages"],
            "last_signal": signal["last_signal"].isoformat(),
        })
    rows.sort(key=lambda row: row["last_signal"], reverse=True)
    if request.GET.get("format") == "json":
        return JsonResponse({"users": rows, "count": len(rows)})
    return render(request, "ml_models/active_users.html", {
        "page_title": "Active Users", "users": rows, "active_count": len(rows),
    })


@farm_access_required
def detection_history_view(request):
    """Detection history page"""
    # Get recent detections
    detections = Detection.objects.select_related('camera', 'model').all()[:50]
    camera = None
    if IPCamera:
        camera = IPCamera.objects.filter(is_active=True).first()
    
    return render(request, 'ml_models/detection_history.html', {
        'detections': detections,
        'camera': camera,
        'page_title': 'Detection History'
    })


@staff_required
def model_management_view(request):
    """Model management page"""
    models = MLModel.objects.all()
    active_model = MLModel.objects.filter(is_active=True).first()
    
    return render(request, 'ml_models/model_management.html', {
        'models': models,
        'active_model': active_model,
        'model_type_choices': MLModel.MODEL_TYPES,
        'category_choices': MLModel.CATEGORY_CHOICES,
        'page_title': 'ML Model Management'
    })


@farm_owner_required
def detect_from_camera_stream(request):
    """Detect objects from camera stream (stub)"""
    from django.http import JsonResponse
    return JsonResponse({
        'status': 'error',
        'message': 'Camera stream detection not yet implemented'
    }, status=501)


@staff_required
def download_model_file(request, pk):
    """
    Authenticated download of a privately-stored model file.

    Model weights live outside MEDIA_ROOT and are never publicly served; this
    view is the only path to them and is restricted to staff (the same
    authorization used for managing models).
    """
    from django.http import FileResponse, Http404, HttpResponseForbidden

    if not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to download model files.")

    model = MLModel.objects.filter(pk=pk).first()
    if not model or not model.model_file:
        raise Http404("Model file not found.")

    try:
        return FileResponse(
            model.model_file.open('rb'),
            as_attachment=True,
            filename=os.path.basename(model.model_file.name),
        )
    except FileNotFoundError:
        raise Http404("Model file is missing from storage.")
