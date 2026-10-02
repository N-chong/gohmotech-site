from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.contrib.auth.hashers import check_password, make_password
import subprocess
import re
import logging
import uuid as uuid_lib
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)


class SmartFarmGoatManager(models.Manager):
    """Keep community marketplace records out of farm and IoT queries."""

    def get_queryset(self):
        return super().get_queryset().filter(record_source="smart_farm")


def normalize_ble_mac_address(value):
    """Return an uppercase, colon-delimited BLE MAC address or ``None``."""
    if value in (None, ''):
        return None

    compact = re.sub(r'[^0-9A-Fa-f]', '', str(value))
    if len(compact) != 12:
        raise ValidationError('Enter a valid BLE MAC address.')
    return ':'.join(compact[index:index + 2] for index in range(0, 12, 2)).upper()


def normalize_ibeacon_uuid(value):
    """Return the canonical uppercase representation of an iBeacon UUID."""
    try:
        return str(uuid_lib.UUID(str(value))).upper()
    except (AttributeError, TypeError, ValueError):
        raise ValidationError('Enter a valid 128-bit iBeacon UUID.')


class Goat(models.Model):
    """Individual Goat Inventory and Identification"""
    BREED_CHOICES = [
        ('boer', 'Boer'),
        ('saanen', 'Saanen'),
        ('alpine', 'Alpine'),
        ('nubian', 'Nubian'),
        ('toggenburg', 'Toggenburg'),
        ('lamancha', 'LaMancha'),
        ('anglo_nubian', 'Anglo-Nubian'),
        ('native', 'Native/Local Breed'),
        ('mixed', 'Mixed Breed'),
        ('other', 'Other'),
    ]
    
    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
    ]
    
    HEALTH_STATUS_CHOICES = [
        ('healthy', 'Healthy'),
        ('monitoring', 'Under Monitoring'),
        ('sick', 'Sick'),
        ('quarantine', 'Quarantined'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('sold', 'Sold'),
        ('dead', 'Dead'),
        ('missing', 'Missing'),
    ]

    VACCINATION_STATUS_CHOICES = [
        ('not_vaccinated', 'Not Vaccinated'),
        ('partially_vaccinated', 'Partially Vaccinated'),
        ('fully_vaccinated', 'Fully Vaccinated'),
        ('unknown', 'Unknown'),
    ]

    SMART_FARM = "smart_farm"
    COMMUNITY = "community"
    RECORD_SOURCE_CHOICES = [
        (SMART_FARM, "GoHMoTech Smart Farm"),
        (COMMUNITY, "Community Seller"),
    ]

    # Basic identification
    goat_id = models.CharField(
        max_length=50, 
        unique=True,
        help_text="Unique identifier (e.g., tag number, RFID)"
    )
    name = models.CharField(
        max_length=100, 
        blank=True,
        help_text="Optional name for the goat"
    )
    tag_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="Physical tag/ear tag number"
    )
    
    # Physical characteristics
    breed = models.CharField(
        max_length=50,
        choices=BREED_CHOICES,
        default='native'
    )
    gender = models.CharField(
        max_length=10,
        choices=GENDER_CHOICES
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        help_text="Approximate or exact date of birth"
    )
    weight_kg = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Current weight in kilograms"
    )
    color_markings = models.CharField(
        max_length=255,
        blank=True,
        help_text="Coat color and distinctive markings (e.g., brown with white patch on forehead)"
    )

    # Health and status
    health_status = models.CharField(
        max_length=20,
        choices=HEALTH_STATUS_CHOICES,
        default='healthy'
    )
    health_notes = models.TextField(
        blank=True,
        help_text="Any health observations or medical notes"
    )

    # Vaccination information
    vaccination_status = models.CharField(
        max_length=25,
        choices=VACCINATION_STATUS_CHOICES,
        default='unknown',
        help_text="Overall vaccination status"
    )
    vaccine_name = models.CharField(
        max_length=150,
        blank=True,
        help_text="Name of the most recent vaccine administered"
    )
    vaccination_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the most recent vaccine was administered"
    )
    next_due_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the next vaccination is due (optional)"
    )

    # General notes
    notes = models.TextField(
        blank=True,
        help_text="General notes or remarks about this goat"
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="owned_goats",
        help_text="Account responsible for this goat record.",
    )
    record_source = models.CharField(
        max_length=20,
        choices=RECORD_SOURCE_CHOICES,
        default=SMART_FARM,
        db_index=True,
        help_text="Separates IoT-integrated farm goats from manual community records.",
    )

    # Inventory status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        db_index=True,
        help_text="Current status of the goat in inventory"
    )
    
    # Tracking
    date_added = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    last_seen = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Last time this goat was detected by AI system"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="False if goat has been sold, died, or removed"
    )
    
    # AI/ML fields (used for monitoring/re-identification only, NOT registration)
    feature_embedding = models.JSONField(
        null=True,
        blank=True,
        help_text="Feature embedding vector for re-identification (128-dim or 1280-dim)"
    )
    embedding_last_updated = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time the feature embedding was updated"
    )

    objects = SmartFarmGoatManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['goat_id']
        indexes = [
            models.Index(fields=['goat_id']),
            models.Index(fields=['is_active', 'health_status']),
            models.Index(fields=['status']),
            models.Index(fields=['last_seen']),
            models.Index(fields=['owner', 'record_source']),
            models.Index(
                fields=['record_source', 'status', 'is_active'],
                name='goat_source_status_idx',
            ),
            models.Index(fields=['breed', 'gender'], name='goat_breed_gender_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(record_source="smart_farm") | models.Q(owner__isnull=False),
                name="community_goat_requires_owner",
            )
        ]
    
    def __str__(self):
        if self.name:
            return f"{self.goat_id} - {self.name}"
        return self.goat_id

    def clean(self):
        super().clean()
        if self.record_source == self.COMMUNITY and not self.owner_id:
            raise ValidationError({"owner": "Community goats must have an account owner."})
    
    @property
    def age_days(self):
        """Calculate age in days"""
        if self.date_of_birth:
            return (timezone.now().date() - self.date_of_birth).days
        return None
    
    @property
    def age_display(self):
        """Human-readable age"""
        if not self.date_of_birth:
            return "Unknown"
        
        days = self.age_days
        if days < 30:
            return f"{days} days"
        elif days < 365:
            months = days // 30
            return f"{months} month{'s' if months > 1 else ''}"
        else:
            years = days // 365
            remaining_months = (days % 365) // 30
            if remaining_months > 0:
                return f"{years} year{'s' if years > 1 else ''}, {remaining_months} month{'s' if remaining_months > 1 else ''}"
            return f"{years} year{'s' if years > 1 else ''}"
    
    @property
    def is_missing(self):
        """Check if goat is marked as missing or not seen recently"""
        if self.status == 'missing':
            return True
        if self.last_seen and self.status == 'active':
            hours_since_seen = (timezone.now() - self.last_seen).total_seconds() / 3600
            return hours_since_seen > 24  # Not seen in 24 hours
        return False
    
    def update_last_seen(self):
        """Update last_seen timestamp to now"""
        self.last_seen = timezone.now()
        self.save(update_fields=['last_seen'])
    
    def update_embedding(self, embedding_vector):
        """Update feature embedding"""
        self.feature_embedding = embedding_vector if isinstance(embedding_vector, list) else embedding_vector.tolist()
        self.embedding_last_updated = timezone.now()
        self.save(update_fields=['feature_embedding', 'embedding_last_updated'])


class GoatWeightMeasurement(models.Model):
    """A farmer-confirmed weight measurement for one explicitly selected goat."""

    SOURCE_LOAD_CELL = 'load_cell'
    SOURCE_MANUAL = 'manual'
    SOURCE_CHOICES = [
        (SOURCE_LOAD_CELL, 'Load Cell'),
        (SOURCE_MANUAL, 'Manual'),
    ]

    goat = models.ForeignKey(
        Goat,
        on_delete=models.CASCADE,
        related_name='weight_measurements',
    )
    weight_kg = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(0.1), MaxValueValidator(300)],
        help_text='Confirmed goat weight in kilograms (0.1 to 300 kg)',
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    measured_at = models.DateTimeField(default=timezone.now, db_index=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recorded_goat_weights',
    )
    device_id = models.CharField(max_length=100, blank=True)
    request_id = models.UUIDField(default=uuid_lib.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ['-measured_at', '-id']
        indexes = [
            models.Index(fields=['goat', '-measured_at']),
            models.Index(fields=['source', '-measured_at']),
        ]

    def __str__(self):
        return f'{self.goat.goat_id}: {self.weight_kg} kg ({self.get_source_display()})'


class GoatImage(models.Model):
    """Images of individual goats for ML training and visual reference"""
    FRONT = 'front'
    LEFT = 'left'
    RIGHT = 'right'
    REAR = 'rear'
    FACE = 'face'
    ANGLE_CHOICES = [
        (FRONT, 'Front View'),
        (LEFT, 'Left Side View'),
        (RIGHT, 'Right Side View'),
        (REAR, 'Rear View'),
        (FACE, 'Face Close-up'),
    ]
    IMAGE_TYPE_CHOICES = [
        ('profile', 'Profile Picture'),
        ('full_body', 'Full Body'),
        ('face', 'Face/Muzzle'),
        ('identification', 'Identification Reference'),
        ('health', 'Health Documentation'),
        ('training', 'ML Training Data'),
    ]
    
    goat = models.ForeignKey(
        Goat,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(
        upload_to='goat_images/%Y/%m/%d/',
        help_text="Upload goat image"
    )
    image_type = models.CharField(
        max_length=20,
        choices=IMAGE_TYPE_CHOICES,
        default='identification'
    )
    angle = models.CharField(
        max_length=10,
        choices=ANGLE_CHOICES,
        null=True,
        blank=True,
        db_index=True,
        help_text='Standardized camera angle; blank preserves legacy/gallery images.',
    )
    captured_at = models.DateTimeField(
        default=timezone.now,
        help_text='When this reference photo was captured or selected.',
    )
    is_primary = models.BooleanField(
        default=False,
        db_index=True,
        help_text='Fallback inventory image when front and left views are unavailable.',
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description or notes about this image"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    # ML processing flags
    is_processed = models.BooleanField(
        default=False,
        help_text="Has this image been processed by ML models?"
    )
    is_training_data = models.BooleanField(
        default=False,
        help_text="Use this image for ML model training"
    )
    
    # Computer vision metadata
    detected_features = models.JSONField(
        null=True,
        blank=True,
        help_text="ML-extracted features (embeddings, keypoints, etc.)"
    )
    
    # Feature embedding for re-identification
    feature_embedding = models.JSONField(
        null=True,
        blank=True,
        help_text="Feature embedding vector extracted from this image"
    )
    embedding_extracted = models.BooleanField(
        default=False,
        help_text="Has feature embedding been extracted from this image?"
    )
    
    class Meta:
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['goat', '-uploaded_at']),
            models.Index(fields=['is_training_data']),
            models.Index(fields=['embedding_extracted']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['goat', 'angle'],
                name='unique_goat_standard_photo_angle',
            ),
        ]
    
    def __str__(self):
        label = self.get_angle_display() if self.angle else self.get_image_type_display()
        return f"{self.goat.goat_id} - {label} ({self.uploaded_at.date()})"

    @classmethod
    def preferred_from(cls, images):
        """Choose a stable inventory cover without breaking legacy galleries."""
        photos = list(images)
        if not photos:
            return None
        newest_first = sorted(
            photos,
            key=lambda photo: (photo.uploaded_at, photo.pk or 0),
            reverse=True,
        )
        for angle in (cls.FRONT, cls.LEFT):
            match = next((photo for photo in newest_first if photo.angle == angle), None)
            if match:
                return match
        return next((photo for photo in newest_first if photo.is_primary), newest_first[0])


class GoatBehaviorLog(models.Model):
    """ML-detected behavior patterns for individual goats"""
    BEHAVIOR_CHOICES = [
        ('grazing', 'Grazing'),
        ('resting', 'Resting'),
        ('walking', 'Walking'),
        ('running', 'Running'),
        ('eating', 'Eating (at feeder)'),
        ('drinking', 'Drinking'),
        ('standing', 'Standing/Idle'),
        ('lying', 'Lying Down'),
        ('abnormal', 'Abnormal Behavior'),
        ('inactive', 'Inactive/Lethargic'),
    ]
    
    goat = models.ForeignKey(
        Goat,
        on_delete=models.CASCADE,
        related_name='behavior_logs',
        null=True,
        blank=True,
        help_text="Specific goat if identified, null for group behavior"
    )
    
    behavior_type = models.CharField(
        max_length=20,
        choices=BEHAVIOR_CHOICES
    )
    
    confidence_score = models.FloatField(
        validators=[MinValueValidator(0)],
        help_text="ML model confidence (0-1)"
    )
    
    # Environmental context
    temperature_celsius = models.FloatField(null=True, blank=True)
    humidity_percent = models.FloatField(null=True, blank=True)
    time_of_day = models.TimeField(null=True, blank=True)
    
    # Detection metadata
    detected_by = models.CharField(
        max_length=100,
        help_text="Camera/device that made the detection"
    )
    detection_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional ML detection metadata"
    )
    
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['goat', '-timestamp']),
            models.Index(fields=['behavior_type', '-timestamp']),
        ]
    
    def __str__(self):
        goat_info = f"{self.goat.goat_id}" if self.goat else "Group"
        return f"{goat_info} - {self.behavior_type} ({self.confidence_score:.2f})"


class GrassHealthLog(models.Model):
    """Computer vision-based grass health monitoring"""
    
    # Location of grass sample
    location = models.CharField(
        max_length=200,
        help_text="Area/zone where grass was analyzed"
    )
    
    # Computer vision metrics
    greenness_index = models.FloatField(
        validators=[MinValueValidator(0)],
        help_text="0-1 scale, derived from RGB analysis"
    )
    vegetation_density = models.FloatField(
        null=True,
        blank=True,
        help_text="0-1 scale, coverage percentage"
    )
    
    # Health assessment
    health_status = models.CharField(
        max_length=20,
        choices=[
            ('excellent', 'Excellent'),
            ('good', 'Good'),
            ('fair', 'Fair'),
            ('poor', 'Poor'),
            ('drought', 'Drought Stressed'),
        ],
        default='fair'
    )
    
    # Environmental data
    temperature_celsius = models.FloatField(null=True, blank=True)
    humidity_percent = models.FloatField(null=True, blank=True)
    soil_moisture_percent = models.FloatField(null=True, blank=True)
    
    # Image reference
    image = models.ImageField(
        upload_to='grass_health/%Y/%m/%d/',
        null=True,
        blank=True
    )
    
    # Detection metadata
    analyzed_by = models.CharField(
        max_length=100,
        help_text="Camera/device that captured the image"
    )
    analysis_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Detailed computer vision analysis results"
    )
    
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['location', '-timestamp']),
            models.Index(fields=['health_status', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.location} - {self.health_status} (Greenness: {self.greenness_index:.2f})"
    
    @property
    def is_drought_stressed(self):
        """Check if grass shows drought stress"""
        return self.health_status == 'drought' or (
            self.greenness_index < 0.3 and 
            self.soil_moisture_percent and 
            self.soil_moisture_percent < 20
        )


class IPCamera(models.Model):
    """WiFi IP Camera configuration for live monitoring"""
    
    CAMERA_TYPE_CHOICES = [
        ('wifi', 'WiFi IP Camera'),
        ('rtsp', 'RTSP Camera'),
        ('http', 'HTTP/MJPEG Camera'),
        ('usb', 'USB Camera'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('error', 'Connection Error'),
    ]
    
    # Basic identification
    camera_id = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique camera identifier (e.g., CAM001)"
    )
    name = models.CharField(
        max_length=200,
        help_text="Descriptive camera name (e.g., 'Barn Entrance Cam')"
    )
    camera_type = models.CharField(
        max_length=20,
        choices=CAMERA_TYPE_CHOICES,
        default='wifi'
    )
    
    # Network configuration
    mac_address = models.CharField(
        max_length=17,
        unique=True,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$',
                message='Enter a valid MAC address (e.g., AA:BB:CC:DD:EE:FF or AA-BB-CC-DD-EE-FF)'
            )
        ],
        help_text="Optional: Camera MAC address for auto IP discovery when IP changes"
    )
    ip_address = models.GenericIPAddressField(
        default='0.0.0.0',
        help_text="Camera IP address (e.g., 192.168.1.100)"
    )
    port = models.IntegerField(
        default=80,
        help_text="Camera port (usually 80, 554 for RTSP, or 8080)"
    )
    username = models.CharField(
        max_length=100,
        blank=True,
        help_text="Camera login username (if required)"
    )
    password = models.CharField(
        max_length=100,
        blank=True,
        help_text="Camera login password (if required)"
    )
    
    # Stream URLs
    rtsp_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="Full RTSP URL (e.g., rtsp://192.168.1.100:554/stream)"
    )
    http_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="HTTP/MJPEG stream URL (e.g., http://192.168.1.100/video)"
    )
    snapshot_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="URL for single snapshot (e.g., http://192.168.1.100/snapshot.jpg)"
    )
    
    # Location and monitoring
    location = models.CharField(
        max_length=200,
        help_text="Physical location (e.g., 'Barn Entrance', 'Feeding Area')"
    )
    description = models.TextField(
        blank=True,
        help_text="Additional notes about camera placement and purpose"
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='inactive'
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Enable/disable this camera"
    )
    
    # ML/Detection settings
    enable_goat_detection = models.BooleanField(
        default=True,
        help_text="Run ML goat detection on this camera feed"
    )
    detection_interval_seconds = models.IntegerField(
        default=30,
        help_text="How often to run detection (in seconds)"
    )
    
    # Metadata
    last_connected = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last successful connection timestamp"
    )
    last_error = models.TextField(
        blank=True,
        help_text="Last error message if connection failed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['location', 'name']
        indexes = [
            models.Index(fields=['camera_id']),
            models.Index(fields=['mac_address']),
            models.Index(fields=['is_active', 'status']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.mac_address})"
    
    def resolve_ip_from_mac(self):
        """
        Resolve current IP address from MAC address using ARP table
        
        Returns:
            str: IP address if found, None otherwise
        """
        try:
            # Normalize MAC address format for comparison
            mac_normalized = self.mac_address.upper().replace('-', ':')
            
            # Windows: use 'arp -a'
            if subprocess.os.name == 'nt':
                result = subprocess.run(['arp', '-a'], capture_output=True, text=True, timeout=5)
                output = result.stdout
                
                # Parse ARP table (format: IP Address       Physical Address      Type)
                # Example: 192.168.1.100    aa-bb-cc-dd-ee-ff     dynamic
                for line in output.split('\n'):
                    if mac_normalized.replace(':', '-') in line.upper() or mac_normalized in line.upper():
                        # Extract IP address
                        ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line)
                        if ip_match:
                            return ip_match.group(1)
            
            # Linux/Unix: use 'arp -n' or 'ip neigh'
            else:
                # Try 'ip neigh' first (modern Linux)
                try:
                    result = subprocess.run(['ip', 'neigh'], capture_output=True, text=True, timeout=5)
                    output = result.stdout
                    
                    for line in output.split('\n'):
                        if mac_normalized in line.upper():
                            ip_match = re.search(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line)
                            if ip_match:
                                return ip_match.group(1)
                except:
                    pass
                
                # Fallback to 'arp -n'
                result = subprocess.run(['arp', '-n'], capture_output=True, text=True, timeout=5)
                output = result.stdout
                
                for line in output.split('\n'):
                    if mac_normalized in line.upper():
                        ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line)
                        if ip_match:
                            return ip_match.group(1)
            
        except Exception as e:
            logger.warning("Error resolving IP from MAC %s: %s", self.mac_address, e)
        
        return None
    
    def update_ip_from_mac(self):
        """
        Update the stored IP address by resolving from MAC address
        
        Returns:
            bool: True if IP was found and updated, False otherwise
        """
        resolved_ip = self.resolve_ip_from_mac()
        if resolved_ip:
            if self.ip_address != resolved_ip:
                self.ip_address = resolved_ip
                self.save(update_fields=['ip_address'])
                logger.info("Updated IP for %s: %s", self.name, resolved_ip)
            return True
        return False
    
    def get_current_ip(self):
        """
        Get current IP address, attempting to resolve from MAC if available
        
        Returns:
            str: Current IP address or None
        """
        # If no MAC address, just use the stored IP (original behavior)
        if not self.mac_address:
            return self.ip_address
        
        # Always try the MAC first.  An abrupt joint power loss leaves the
        # database status as ``active`` even though DHCP may assign a different
        # address during the next boot.
        resolved_ip = self.resolve_ip_from_mac()
        if resolved_ip:
            # Update stored IP if different
            if self.ip_address != resolved_ip:
                self.ip_address = resolved_ip
                self.save(update_fields=['ip_address'])
            return resolved_ip
        
        # Fall back to stored IP even if stale
        return self.ip_address
    
    def get_stream_url(self):
        """Get the appropriate stream URL based on camera type"""
        if self.rtsp_url:
            return self._url_with_current_ip(self.rtsp_url)
        elif self.http_url:
            return self._url_with_current_ip(self.http_url)
        else:
            # Get current IP (resolves from MAC if needed)
            ip_address = self.get_current_ip()
            if not ip_address:
                return None
            
            # Construct default URLs based on IP and credentials
            if self.camera_type == 'rtsp':
                auth = f"{self.username}:{self.password}@" if self.username else ""
                return f"rtsp://{auth}{ip_address}:{self.port}/stream"
            elif self.camera_type in ['wifi', 'http']:
                auth = f"{self.username}:{self.password}@" if self.username else ""
                return f"http://{auth}{ip_address}:{self.port}/video"
        return None

    def _url_with_current_ip(self, configured_url):
        """Keep a configured path/credentials while following a DHCP address.

        Camera URLs historically stored the IP in two places: ``ip_address``
        and the full stream URL.  Replacing only ``ip_address`` therefore did
        not affect reconnects.  A configured MAC makes it safe to substitute
        the currently resolved host without exposing or rebuilding credentials.
        """
        if not configured_url or not self.mac_address:
            return configured_url

        current_ip = self.get_current_ip()
        if not current_ip:
            return configured_url

        try:
            parsed = urlsplit(configured_url)
            if not parsed.hostname or parsed.hostname == current_ip:
                return configured_url

            userinfo, separator, _ = parsed.netloc.rpartition('@')
            prefix = f'{userinfo}{separator}' if separator else ''
            host = f'[{current_ip}]' if ':' in current_ip else current_ip
            port = f':{parsed.port}' if parsed.port else ''
            return urlunsplit(parsed._replace(netloc=f'{prefix}{host}{port}'))
        except (TypeError, ValueError):
            logger.warning('Could not update the stream host for camera %s', self.name)
            return configured_url
    
    def get_snapshot_url(self):
        """Get the snapshot URL"""
        if self.snapshot_url:
            return self.snapshot_url
        else:
            # Get current IP (resolves from MAC if needed)
            ip_address = self.get_current_ip()
            if not ip_address:
                return None
            
            auth = f"{self.username}:{self.password}@" if self.username else ""
            return f"http://{auth}{ip_address}:{self.port}/snapshot.jpg"
    
    def mark_online(self):
        """Mark camera as online and update last_connected timestamp"""
        self.status = 'active'
        self.last_connected = timezone.now()
        self.last_error = ''
        self.save(update_fields=['status', 'last_connected', 'last_error'])
    
    def mark_offline(self, error_message=''):
        """Mark camera as offline with optional error message"""
        self.status = 'error' if error_message else 'inactive'
        self.last_error = error_message
        self.save(update_fields=['status', 'last_error'])


class GoatDetectionHistory(models.Model):
    """Track individual goat detections over time for identification and behavior analysis"""
    
    goat = models.ForeignKey(
        Goat,
        on_delete=models.CASCADE,
        related_name='detection_history',
        null=True,
        blank=True,
        help_text="Identified goat (null if unidentified)"
    )
    camera = models.ForeignKey(
        IPCamera,
        on_delete=models.CASCADE,
        related_name='goat_detections'
    )
    
    # Detection details
    bounding_box = models.JSONField(
        help_text="Bounding box coordinates: {x, y, width, height}"
    )
    detection_confidence = models.FloatField(
        validators=[MinValueValidator(0)],
        help_text="YOLOv8 detection confidence (0-1)"
    )
    
    # Re-identification details
    identification_confidence = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Re-identification confidence score (0-1)"
    )
    feature_embedding = models.JSONField(
        null=True,
        blank=True,
        help_text="Feature embedding vector extracted from this detection"
    )
    similarity_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Cosine similarity score with matched goat"
    )
    
    # Metadata
    is_new_goat = models.BooleanField(
        default=False,
        help_text="True if this detection resulted in auto-registration"
    )
    crop_image = models.ImageField(
        upload_to='detection_crops/%Y/%m/%d/',
        null=True,
        blank=True,
        help_text="Cropped image of detected goat"
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Goat Detection History"
        verbose_name_plural = "Goat Detection Histories"
        indexes = [
            models.Index(fields=['goat', '-timestamp']),
            models.Index(fields=['camera', '-timestamp']),
            models.Index(fields=['-timestamp']),
            models.Index(fields=['is_new_goat']),
        ]
    
    def __str__(self):
        goat_info = f"{self.goat.goat_id}" if self.goat else "Unidentified"
        return f"{goat_info} detected at {self.timestamp} (conf: {self.identification_confidence or 0:.2f})"


class MissingGoatAlert(models.Model):
    """Alert system for missing goats and count mismatches"""
    
    ALERT_TYPE_CHOICES = [
        ('count_mismatch', 'Count Mismatch'),
        ('not_seen_recently', 'Not Seen Recently'),
        ('door_automation', 'Door Automation Check'),
        ('manual', 'Manual Alert'),
    ]
    
    SEVERITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    
    # Alert details
    alert_type = models.CharField(
        max_length=30,
        choices=ALERT_TYPE_CHOICES,
        default='count_mismatch'
    )
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default='medium'
    )
    title = models.CharField(
        max_length=200,
        help_text="Alert title/summary"
    )
    message = models.TextField(
        help_text="Detailed alert message"
    )
    
    # Goat count information
    expected_count = models.IntegerField(
        help_text="Expected number of active goats"
    )
    detected_count = models.IntegerField(
        help_text="Number of goats actually detected"
    )
    missing_count = models.IntegerField(
        default=0,
        help_text="Number of missing goats (expected - detected)"
    )
    
    # Related objects
    camera = models.ForeignKey(
        IPCamera,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='missing_goat_alerts'
    )
    missing_goats = models.ManyToManyField(
        Goat,
        blank=True,
        related_name='missing_alerts',
        help_text="Specific goats identified as missing"
    )
    
    # Status tracking
    is_resolved = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Has this alert been resolved?"
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the alert was resolved"
    )
    resolved_by = models.CharField(
        max_length=100,
        blank=True,
        help_text="User or system that resolved the alert"
    )
    resolution_notes = models.TextField(
        blank=True,
        help_text="Notes about how the alert was resolved"
    )
    
    # Notification tracking
    notification_sent = models.BooleanField(
        default=False,
        help_text="Has notification been sent?"
    )
    notification_sent_at = models.DateTimeField(
        null=True,
        blank=True
    )
    
    # Automation action
    automation_action_taken = models.CharField(
        max_length=100,
        blank=True,
        help_text="Action taken by automation system (e.g., 'door_hold', 'door_closed')"
    )
    
    # Metadata
    metadata = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional context data (detection results, environmental conditions, etc.)"
    )
    triggered_at = models.DateTimeField(default=timezone.now, db_index=True)
    
    class Meta:
        ordering = ['-triggered_at']
        verbose_name = "Missing Goat Alert"
        verbose_name_plural = "Missing Goat Alerts"
        indexes = [
            models.Index(fields=['-triggered_at']),
            models.Index(fields=['is_resolved', '-triggered_at']),
            models.Index(fields=['severity', '-triggered_at']),
            models.Index(fields=['alert_type']),
        ]
    
    def __str__(self):
        status = "Resolved" if self.is_resolved else "Active"
        return f"[{status}] {self.title} - {self.severity.upper()} ({self.triggered_at.strftime('%Y-%m-%d %H:%M')})"
    
    def resolve(self, resolved_by=None, notes=''):
        """Mark alert as resolved"""
        self.is_resolved = True
        self.resolved_at = timezone.now()
        self.resolved_by = resolved_by or 'system'
        self.resolution_notes = notes
        self.save(update_fields=['is_resolved', 'resolved_at', 'resolved_by', 'resolution_notes'])
    
    def calculate_missing_count(self):
        """Calculate and update missing count"""
        self.missing_count = max(0, self.expected_count - self.detected_count)
        self.save(update_fields=['missing_count'])


class NotificationLog(models.Model):
    """Log of all notifications sent by the system"""
    
    NOTIFICATION_TYPE_CHOICES = [
        ('missing_goat', 'Missing Goat Alert'),
        ('health', 'Health Alert'),
        ('door_automation', 'Door Automation'),
        ('system', 'System Notification'),
        ('detection', 'Detection Event'),
    ]
    
    CHANNEL_CHOICES = [
        ('websocket', 'WebSocket (Dashboard)'),
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('in_app', 'In-App Notification'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]
    
    # Notification details
    notification_type = models.CharField(
        max_length=30,
        choices=NOTIFICATION_TYPE_CHOICES
    )
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        default='websocket'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    # Content
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Recipients
    recipient = models.CharField(
        max_length=200,
        help_text="Email address, phone number, or user ID"
    )
    
    # Related objects
    alert = models.ForeignKey(
        MissingGoatAlert,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )
    
    # Delivery tracking
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the notification was successfully sent"
    )
    error_message = models.TextField(
        blank=True,
        help_text="Error message if delivery failed"
    )
    retry_count = models.IntegerField(
        default=0,
        help_text="Number of delivery attempts"
    )
    
    # Metadata
    metadata = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional notification data"
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Notification Log"
        verbose_name_plural = "Notification Logs"
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['channel', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_channel_display()} - {self.title} ({self.status})"
    
    def mark_sent(self):
        """Mark notification as sent"""
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.save(update_fields=['status', 'sent_at'])
    
    def mark_failed(self, error_message=''):
        """Mark notification as failed"""
        self.status = 'failed'
        self.error_message = error_message
        self.retry_count += 1
        self.save(update_fields=['status', 'error_message', 'retry_count'])


class BLEBeacon(models.Model):
    """Physical BLE/iBeacon tracker that may be assigned to one goat."""

    goat = models.OneToOneField(
        Goat,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ble_beacon',
        help_text='Goat currently assigned to this tracker. Trackers may remain unassigned.'
    )
    device_name = models.CharField(max_length=100, blank=True)
    mac_address = models.CharField(
        max_length=17,
        unique=True,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$',
                message='Enter a valid MAC address (for example AA:BB:CC:DD:EE:FF).'
            )
        ],
        help_text='Optional platform-visible BLE address. Stored in uppercase colon format.'
    )
    uuid = models.CharField(
        max_length=36,
        help_text='Canonical iBeacon proximity UUID.'
    )
    major = models.PositiveSmallIntegerField(
        validators=[MaxValueValidator(65535)],
        help_text='Farm or herd identifier (0-65535).'
    )
    minor = models.PositiveSmallIntegerField(
        validators=[MaxValueValidator(65535)],
        help_text='Individual beacon/goat identifier (0-65535).'
    )
    calibrated_rssi = models.SmallIntegerField(
        default=-59,
        validators=[MinValueValidator(-127), MaxValueValidator(20)],
        help_text='Measured RSSI at one metre, in dBm.'
    )
    advertising_interval_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(20), MaxValueValidator(10240)],
        help_text='Configured advertising interval in milliseconds, when known.'
    )
    tx_power_dbm = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Configured transmitter power in dBm, when known.'
    )
    battery_level = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MaxValueValidator(100)],
        help_text='Most recently reported battery percentage, when advertised.'
    )
    battery_updated_at = models.DateTimeField(null=True, blank=True)
    enabled = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['device_name', 'major', 'minor']
        verbose_name = 'BLE Beacon'
        verbose_name_plural = 'BLE Beacons'
        constraints = [
            models.UniqueConstraint(
                fields=['uuid', 'major', 'minor'],
                name='unique_ibeacon_identity'
            ),
        ]
        indexes = [
            models.Index(fields=['uuid', 'major', 'minor']),
            models.Index(fields=['enabled', 'updated_at']),
        ]

    def __str__(self):
        identity = f'{self.uuid} / {self.major} / {self.minor}'
        return f'{self.device_name or identity} -> {self.goat or "Unassigned"}'

    def clean(self):
        super().clean()
        if self.uuid:
            self.uuid = normalize_ibeacon_uuid(self.uuid)
        self.mac_address = normalize_ble_mac_address(self.mac_address)

    def save(self, *args, **kwargs):
        self.uuid = normalize_ibeacon_uuid(self.uuid)
        self.mac_address = normalize_ble_mac_address(self.mac_address)
        return super().save(*args, **kwargs)


class BLEReceiver(models.Model):
    """BLE scanner metadata extending the existing generic IoT Device model."""

    PLATFORM_CHOICES = [
        ('windows', 'Windows'),
        ('linux', 'Linux'),
        ('raspberry_pi', 'Raspberry Pi'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('error', 'Error'),
    ]

    device = models.OneToOneField(
        'iot.Device',
        on_delete=models.CASCADE,
        related_name='ble_receiver'
    )
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='windows')
    device_name = models.CharField(
        max_length=200,
        blank=True,
        help_text='Operating-system device or host name.'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='offline',
        db_index=True
    )
    last_online = models.DateTimeField(null=True, blank=True, db_index=True)
    scanner_version = models.CharField(max_length=50, blank=True)
    api_key_hash = models.CharField(
        max_length=128,
        blank=True,
        editable=False,
        help_text='One-way hash of the receiver ingestion credential.'
    )
    last_error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['device__name']
        verbose_name = 'BLE Receiver'
        verbose_name_plural = 'BLE Receivers'

    def __str__(self):
        return f'{self.device.name} ({self.get_platform_display()})'

    def set_api_key(self, raw_api_key):
        """Store a one-way hash; the raw receiver credential is never persisted."""
        if not raw_api_key:
            raise ValueError('Receiver API key cannot be empty.')
        self.api_key_hash = make_password(raw_api_key)

    def check_api_key(self, raw_api_key):
        """Use Django's timing-safe password hasher verification."""
        return bool(
            raw_api_key
            and self.api_key_hash
            and check_password(raw_api_key, self.api_key_hash)
        )


class BLETrackingState(models.Model):
    """Latest observation state for one beacon as seen by one receiver."""

    PROXIMITY_CHOICES = [
        ('very_near', 'Very Near'),
        ('near', 'Near'),
        ('medium', 'Medium'),
        ('far', 'Far'),
        ('out_of_range', 'Out of Range'),
    ]
    STATUS_CHOICES = [
        ('detected', 'Detected'),
        ('possibly_lost', 'Possibly Lost'),
        ('out_of_range', 'Out of Range'),
    ]

    beacon = models.ForeignKey(
        BLEBeacon,
        on_delete=models.CASCADE,
        related_name='tracking_states'
    )
    receiver = models.ForeignKey(
        BLEReceiver,
        on_delete=models.CASCADE,
        related_name='tracking_states'
    )
    current_rssi = models.SmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-127), MaxValueValidator(20)]
    )
    smoothed_rssi = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-127), MaxValueValidator(20)]
    )
    proximity = models.CharField(
        max_length=20,
        choices=PROXIMITY_CHOICES,
        default='out_of_range',
        db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='out_of_range',
        db_index=True
    )
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)
    sample_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_seen']
        verbose_name = 'BLE Tracking State'
        verbose_name_plural = 'BLE Tracking States'
        constraints = [
            models.UniqueConstraint(
                fields=['beacon', 'receiver'],
                name='unique_ble_beacon_receiver_state'
            ),
        ]
        indexes = [
            models.Index(fields=['receiver', 'status', '-last_seen']),
            models.Index(fields=['beacon', '-last_seen']),
        ]

    def __str__(self):
        return f'{self.beacon} at {self.receiver}: {self.get_status_display()}'


class BLEObservation(models.Model):
    """Throttled BLE detection snapshot; not one row per advertisement."""

    beacon = models.ForeignKey(
        BLEBeacon,
        on_delete=models.CASCADE,
        related_name='observations'
    )
    goat = models.ForeignKey(
        Goat,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ble_observations',
        help_text='Assignment snapshot retained if the beacon is later reassigned.'
    )
    receiver = models.ForeignKey(
        BLEReceiver,
        on_delete=models.CASCADE,
        related_name='observations'
    )
    rssi = models.SmallIntegerField(
        validators=[MinValueValidator(-127), MaxValueValidator(20)]
    )
    smoothed_rssi = models.FloatField(
        validators=[MinValueValidator(-127), MaxValueValidator(20)]
    )
    proximity = models.CharField(
        max_length=20,
        choices=BLETrackingState.PROXIMITY_CHOICES,
        db_index=True
    )
    detected_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-detected_at']
        verbose_name = 'BLE Observation'
        verbose_name_plural = 'BLE Observations'
        indexes = [
            models.Index(fields=['beacon', 'receiver', '-detected_at']),
            models.Index(fields=['goat', '-detected_at']),
        ]

    def __str__(self):
        return f'{self.beacon} / {self.receiver}: {self.rssi} dBm'


class BLETrackingSettings(models.Model):
    """Database-backed calibration and retention settings for BLE tracking."""

    SMOOTHING_CHOICES = [
        ('median', 'Rolling Median'),
        ('moving_average', 'Moving Average'),
    ]

    smoothing_method = models.CharField(
        max_length=20,
        choices=SMOOTHING_CHOICES,
        default='median'
    )
    smoothing_window_size = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(3), MaxValueValidator(50)]
    )
    very_near_min_rssi = models.SmallIntegerField(default=-50)
    near_min_rssi = models.SmallIntegerField(default=-60)
    medium_min_rssi = models.SmallIntegerField(default=-70)
    possibly_lost_timeout_seconds = models.PositiveIntegerField(
        default=8,
        validators=[MinValueValidator(1)]
    )
    out_of_range_timeout_seconds = models.PositiveIntegerField(
        default=20,
        validators=[MinValueValidator(2)]
    )
    report_interval_seconds = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(60)]
    )
    heartbeat_interval_seconds = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(300)]
    )
    history_snapshot_interval_seconds = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1)]
    )
    history_retention_days = models.PositiveIntegerField(
        default=90,
        validators=[MinValueValidator(1)]
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = 'BLE Tracking Settings'
        verbose_name_plural = 'BLE Tracking Settings'

    def __str__(self):
        return 'BLE Tracking Settings'

    def clean(self):
        super().clean()
        if not (
            self.very_near_min_rssi > self.near_min_rssi > self.medium_min_rssi
        ):
            raise ValidationError(
                'RSSI thresholds must descend from Very Near to Near to Medium.'
            )
        if self.possibly_lost_timeout_seconds >= self.out_of_range_timeout_seconds:
            raise ValidationError(
                'Possibly Lost timeout must be shorter than Out of Range timeout.'
            )

    def save(self, *args, **kwargs):
        self.pk = 1
        self.full_clean()
        return super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config
