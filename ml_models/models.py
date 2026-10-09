from django.db import models
from django.conf import settings
from django.utils import timezone
from iot.models import Device


def _protected_model_storage():
    """Callable storage (migration-safe) for private model files."""
    from .storage import protected_model_storage
    return protected_model_storage


class MLModel(models.Model):
    """Machine Learning Model metadata.

    NOTE: this is intentionally NOT goat-specific. Models of any category
    (goat detection, person detection, face detection, or other) can be
    registered here; `category` records what a model is for. The detector
    factory (ml_utils.get_detector) already dispatches purely on `model_type`,
    so new categories require no code change.
    """
    MODEL_TYPES = [
        ('yolov8', 'YOLOv8 (Ultralytics)'),
        ('rfdetr', 'RF-DETR (auto-detect checkpoint)'),
        ('roboflow', 'Roboflow Inference (Self-hosted)'),
        ('roboflow-hosted', 'Roboflow Hosted API'),
        ('yolo', 'YOLO (TensorFlow/Keras)'),
        ('pytorch', 'PyTorch Model'),
        ('sklearn', 'scikit-learn'),
        ('tensorflow', 'TensorFlow/Keras'),
    ]

    # What the model is used for. Deliberately open-ended so the system is not
    # hard-coded to only accept goat models.
    CATEGORY_CHOICES = [
        ('goat', 'Goat Detection'),
        ('person', 'Person Detection'),
        ('face', 'Face Detection'),
        ('other', 'Other'),
    ]

    # Lifecycle status, separate from `is_active`. An uploaded model must be
    # explicitly validated and activated; it is never auto-activated.
    STATUS_CHOICES = [
        ('uploaded', 'Uploaded (pending validation)'),
        ('validated', 'Validated'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('archived', 'Archived'),
        ('rejected', 'Rejected (failed validation)'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default='goat', db_index=True,
        help_text="What this model detects"
    )
    model_type = models.CharField(max_length=100, choices=MODEL_TYPES, default='yolo')
    version = models.CharField(max_length=50)

    # Legacy string path (still read by get_active_detector). Retained for
    # backward compatibility with models registered before file uploads.
    file_path = models.CharField(
        max_length=500, blank=True,
        help_text="Path to model file (.h5, .pt, .pkl). Legacy/manual entries."
    )
    # Securely-stored uploaded model file. Uses a storage backend rooted
    # OUTSIDE MEDIA_ROOT (see storage.ProtectedModelStorage) so model weights
    # are never publicly served; downloads go through an authenticated view.
    model_file = models.FileField(
        upload_to='%Y/%m/', null=True, blank=True,
        storage=_protected_model_storage,
        help_text="Uploaded, validated model file (stored privately)"
    )
    file_size = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="Size of the uploaded file in bytes"
    )

    is_active = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='uploaded', db_index=True
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploaded_ml_models'
    )
    validation_notes = models.TextField(
        blank=True, help_text="Result of automatic/manual validation checks"
    )

    accuracy = models.FloatField(null=True, blank=True, help_text="Model accuracy (0-1)")
    input_size = models.JSONField(default=dict, help_text="Model input dimensions, e.g., {'width': 640, 'height': 640}")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['name', 'version']

    def __str__(self):
        return f"{self.name} v{self.version} ({self.model_type})"

    @property
    def effective_path(self):
        """Path to the model weights, preferring the uploaded file."""
        if self.model_file:
            return self.model_file.path
        return self.file_path



class Detection(models.Model):
    """Goat detection results from ML model"""
    model = models.ForeignKey(
        MLModel,
        on_delete=models.SET_NULL,
        null=True,
        related_name='detections'
    )
    camera = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='detections',
        limit_choices_to={'device_type': 'camera'},
        null=True,
        blank=True
    )
    image_url = models.CharField(max_length=500, blank=True)
    goat_count = models.IntegerField(default=0)
    confidence = models.FloatField(
        help_text="Average confidence score (0-1)"
    )
    bounding_boxes = models.JSONField(
        default=list,
        help_text="List of detected boxes: [{x, y, width, height, confidence, class}]"
    )
    processed = models.BooleanField(default=False)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
        ]

    def __str__(self):
        camera_name = self.camera.name if self.camera else "Test Upload"
        return f"{camera_name} - {self.goat_count} goats detected at {self.timestamp}"

    @property
    def has_detections(self):
        """Check if any goats were detected"""
        return self.goat_count > 0
