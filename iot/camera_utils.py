"""
Camera Streaming Utilities
Handles video capture, streaming, and reconnection logic for IoT Cameras
"""

import cv2
import logging
import re
import threading
import time
from urllib.parse import urlsplit
from django.db import close_old_connections

logger = logging.getLogger(__name__)


def describe_stream_url(stream_url):
    """Return a useful endpoint description without credentials or query values."""
    if not stream_url:
        return "unconfigured endpoint"
    try:
        parsed = urlsplit(stream_url)
        host = parsed.hostname or "unknown-host"
        port = f":{parsed.port}" if parsed.port else ""
        path = re.sub(r'(?<=_password=)[^/]*?(?=_channel=)', '[redacted]', parsed.path or "/")
        return f"{parsed.scheme or 'unknown'}://{host}{port}{path}"
    except (TypeError, ValueError):
        return "invalid endpoint"


class CameraStream:
    """
    Manages video streaming from an IP camera with automatic reconnection
    """
    
    def __init__(self, camera_obj):
        """
        Initialize camera stream
        
        Args:
            camera_obj: IPCamera model instance
        """
        self.camera = camera_obj
        self.stream_url = camera_obj.get_stream_url()
        self.capture = None
        self.frame = None
        self.is_running = False
        self.lock = threading.Lock()
        self.thread = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3  # Reduced from 5 to 3
        self.reconnect_delay = 5  # Increased from 3 to 5 seconds
        self.last_frame_time = time.time()
        self.frame_timeout = 10  # Consider stream dead if no frame for 10 seconds
        self.frame_skip = 1  # No frame skipping for single camera (1 = no skip)
        self.frame_counter = 0
        self.connection_state = 'idle'
        self.connection_error = ''
        self.open_timeout_ms = 8000
        self.read_timeout_ms = 8000
        self.frame_sequence = 0
        self.last_frame_monotonic = None
        self.jpeg_cache = {}
        self.encode_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.last_progress_log = time.monotonic()
        self.source_pts = None
        self.source_pts_changed_at = None
        self.source_pts_advancing = False
        self.last_consumer_at = time.monotonic()
        self.idle_timeout = 90
        self.persistent = False

    def _publish_frame(self, frame):
        with self.lock:
            self.frame = frame
            self.last_frame_time = time.time()
            self.last_frame_monotonic = time.monotonic()
            self.frame_sequence += 1
            self.jpeg_cache.clear()

    def _invalidate_frame(self):
        with self.lock:
            self.frame = None
            self.jpeg_cache.clear()

    def _mark_status(self, online, message=''):
        # Capture threads outlive HTTP requests, so Django's request-bound DB
        # connection cleanup does not run here. A DB hiccup must not kill video.
        try:
            close_old_connections()
            if online:
                self.camera.mark_online()
            else:
                self.camera.mark_offline(message)
        except Exception as error:
            logger.warning('Camera %s status persistence failed (%s); capture continues',
                           self.camera.name, type(error).__name__)
            close_old_connections()
    
    def start(self):
        """Start the camera stream in a separate thread"""
        if self.thread and self.thread.is_alive():
            return False
        if not self.is_running:
            self.last_consumer_at = time.monotonic()
            self.is_running = True
            self.stop_event.clear()
            self.connection_state = 'connecting'
            self.connection_error = ''
            logger.info(
                "Starting camera stream %s (%s)",
                self.camera.name,
                describe_stream_url(self.stream_url),
            )
            self.thread = threading.Thread(target=self._update_frame, daemon=True)
            self.thread.start()
            return True
        return False
    
    def stop(self):
        """Stop the camera stream"""
        self.is_running = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        if self.capture and (not self.thread or not self.thread.is_alive()):
            self.capture.release()
            self.capture = None
        self.connection_state = 'stopped'
        logger.info("Stopped camera stream %s", self.camera.name)
    
    def _connect(self):
        """
        Attempt to connect to the camera
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            # Do not keep retrying an endpoint captured before DHCP or an admin
            # update.  Refreshing here also lets IPCamera resolve its stored MAC
            # after the camera has finished booting and entered the ARP table.
            refresh = getattr(self.camera, 'refresh_from_db', None)
            if callable(refresh):
                try:
                    refresh()
                except Exception as error:
                    logger.warning(
                        'Camera %s configuration refresh failed (%s); using cached settings',
                        self.camera.name,
                        type(error).__name__,
                    )
            self.stream_url = self.camera.get_stream_url()

            # Release previous capture if exists
            self.source_pts = None
            self.source_pts_changed_at = None
            self.source_pts_advancing = False
            if self.capture:
                self.capture.release()
                self.capture = None
            
            self.connection_state = (
                'reconnecting' if self.reconnect_attempts else 'connecting'
            )
            self.connection_error = ''
            logger.info(
                "Connecting to camera %s at %s (attempt %s/%s)",
                self.camera.name,
                describe_stream_url(self.stream_url),
                self.reconnect_attempts + 1,
                self.max_reconnect_attempts,
            )

            if not self.stream_url:
                self.connection_state = 'unavailable'
                self.connection_error = 'Camera stream is not configured.'
                self._mark_status(False, self.connection_error)
                logger.error("Camera %s has no configured stream URL", self.camera.name)
                return False
            
            # These FFmpeg properties bound network stalls during connect/read.
            capture_params = [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                self.open_timeout_ms,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                self.read_timeout_ms,
            ]
            self.capture = cv2.VideoCapture(
                self.stream_url, cv2.CAP_FFMPEG, capture_params
            )
            
            # Critical settings to reduce latency and enable real-time streaming
            # Best-effort only: FFmpeg may ignore this property. Continuous
            # draining below, not this setting, prevents our own frame backlog.
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Check if opened
            if not self.capture.isOpened():
                self.connection_state = 'unavailable'
                self.connection_error = 'Unable to open the camera stream.'
                self._mark_status(False, self.connection_error)
                logger.warning(
                    "Unable to open camera %s at %s; check RTSP endpoint, "
                    "authentication, and decoder output",
                    self.camera.name,
                    describe_stream_url(self.stream_url),
                )
                return False
            
            # Try to read a test frame with timeout
            ret, frame = self.capture.read()
            if ret and frame is not None:
                self.reconnect_attempts = 0
                self.last_frame_time = time.time()
                self._publish_frame(frame)
                self.connection_state = 'online'
                self.connection_error = ''
                self._mark_status(True)
                logger.info(
                    "Camera %s connected; first frame received (%sx%s) via %s",
                    self.camera.name,
                    frame.shape[1],
                    frame.shape[0],
                    self.capture.getBackendName(),
                )
                return True
            
            self.connection_state = 'unavailable'
            self.connection_error = 'Connected, but no video frame was received.'
            self._mark_status(False, self.connection_error)
            logger.warning(
                "Camera %s opened but did not deliver its first frame",
                self.camera.name,
            )
            return False
            
        except Exception as e:
            self.connection_state = 'unavailable'
            self.connection_error = 'Camera connection failed.'
            logger.exception(
                "Camera %s connection raised %s",
                self.camera.name,
                type(e).__name__,
            )
            self._mark_status(False, self.connection_error)
            return False
    
    def _update_frame(self):
        """
        Continuously update frames from the camera (runs in separate thread)
        Handles automatic reconnection on failure
        """
        while self.is_running:
            # A feed opened by a browser should not keep decoding RTSP after
            # every viewer has gone. Explicit camera-start controls pin it.
            if not self.persistent and time.monotonic() - self.last_consumer_at > self.idle_timeout:
                logger.info('Stopping idle camera stream %s after %ss without consumers',
                            self.camera.name, self.idle_timeout)
                self.is_running = False
                self.stop_event.set()
                break
            # Connect if not connected
            if not self.capture or not self.capture.isOpened():
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    if self._connect():
                        continue
                    else:
                        self.reconnect_attempts += 1
                        logger.warning(
                            "Camera %s connection failed; retry %s/%s in %ss",
                            self.camera.name,
                            self.reconnect_attempts,
                            self.max_reconnect_attempts,
                            self.reconnect_delay,
                        )
                        self.connection_state = 'reconnecting'
                        self._invalidate_frame()
                        self.stop_event.wait(min(30, self.reconnect_delay * max(1, self.reconnect_attempts)))
                        continue
                else:
                    logger.error("Max reconnection attempts reached for %s", self.camera.name)
                    self.connection_state = 'unavailable'
                    self.connection_error = 'Camera stream unavailable; retrying shortly.'
                    self._mark_status(False, self.connection_error)
                    self.stop_event.wait(30)
                    self.reconnect_attempts = 0
                    continue
            
            # Read frame from camera
            ret = False
            try:
                # Frame skipping to reduce CPU load with multiple cameras
                self.frame_counter += 1
                if self.frame_counter % self.frame_skip != 0:
                    self.capture.grab()  # Grab and discard frame
                    time.sleep(0.05)  # Small delay
                    continue
                
                # For real-time streaming: grab only 1 frame to clear buffer
                grabbed = self.capture.grab()
                
                # Decode the latest frame
                ret, frame = self.capture.retrieve() if grabbed else (False, None)

                # FFmpeg presentation timestamps can expose a frozen source even
                # when read() succeeds. Enable only after observed progression;
                # unsupported backends commonly return a constant zero.
                pts_property = getattr(cv2, 'CAP_PROP_PTS', None)
                if ret and pts_property is not None and hasattr(self.capture, 'get'):
                    pts = self.capture.get(pts_property)
                    now = time.monotonic()
                    if pts != self.source_pts:
                        if self.source_pts is not None:
                            self.source_pts_advancing = True
                        self.source_pts = pts
                        self.source_pts_changed_at = now
                    elif self.source_pts_advancing and now - self.source_pts_changed_at > self.frame_timeout:
                        logger.warning('Camera %s source timestamp stalled at sequence %s', getattr(self.camera, 'id', self.camera.name), self.frame_sequence)
                        self._invalidate_frame()
                        self.capture.release()
                        self.capture = None
                        self.connection_state = 'reconnecting'
                        continue
                
                if ret and frame is not None:
                    # Downscale large frames to reduce memory pressure
                    height, width = frame.shape[:2]
                    max_width = 1280
                    if width > max_width:
                        scale = max_width / float(width)
                        frame = cv2.resize(frame, (max_width, int(height * scale)))

                    # Update frame with thread lock
                    self._publish_frame(frame)
                    self.connection_state = 'online'
                    self.connection_error = ''
                    if time.monotonic() - self.last_progress_log >= 30:
                        logger.info('Camera %s receiving frames: sequence=%s dimensions=%sx%s',
                                    getattr(self.camera, 'id', self.camera.name), self.frame_sequence,
                                    frame.shape[1], frame.shape[0])
                        self.last_progress_log = time.monotonic()
                    
                    # Mark camera as online
                    if self.camera.status != 'active':
                        self._mark_status(True)
                else:
                    # Check if we've timed out
                    if time.time() - self.last_frame_time > self.frame_timeout:
                        logger.warning("Frame timeout for %s", self.camera.name)
                        self.connection_state = 'reconnecting'
                        self.connection_error = 'Video frames timed out; reconnecting.'
                        self._invalidate_frame()
                        if self.capture:
                            self.capture.release()
                            self.capture = None
                        self._mark_status(False, self.connection_error)
                    
            except Exception as e:
                self.connection_state = 'reconnecting'
                self.connection_error = 'Video read failed; reconnecting.'
                self._invalidate_frame()
                logger.exception(
                    "Camera %s frame read raised %s",
                    self.camera.name,
                    type(e).__name__,
                )
                if self.capture:
                    self.capture.release()
                    self.capture = None
                self.stop_event.wait(1)
            
            # Minimal delay for real-time performance - optimized for single camera
            # Drain the source at its own pace; sleeping after reads queues RTSP
            # frames and adds latency. Delivery FPS is limited by the clients.
            if not ret:
                self.stop_event.wait(0.05)

        if self.capture:
            self.capture.release()
            self.capture = None
        close_old_connections()
    
    def get_frame(self):
        """
        Get the latest frame from the camera
        
        Returns:
            numpy.ndarray or None: Current frame or None if unavailable
        """
        self.last_consumer_at = time.monotonic()
        with self.lock:
            if (self.frame is None or self.last_frame_monotonic is None
                    or time.monotonic() - self.last_frame_monotonic > self.frame_timeout):
                return None

            try:
                return self.frame.copy()
            except Exception as e:
                logger.exception("Error copying frame for %s: %s", self.camera.name, e)
                return None
    
    def get_jpeg_frame(self, quality=85):
        return self.get_jpeg_packet(quality)[1]

    def get_jpeg_packet(self, quality=85, max_width=1280, include_captured_at=False):
        """Encode once per source frame/quality, shared by all viewers."""
        self.last_consumer_at = time.monotonic()
        with self.encode_lock:
            with self.lock:
                sequence = self.frame_sequence
                captured_at = self.last_frame_time
                fresh = (self.frame is not None and self.last_frame_monotonic is not None
                         and time.monotonic() - self.last_frame_monotonic <= self.frame_timeout)
                if not fresh:
                    return (sequence, None, captured_at) if include_captured_at else (sequence, None)
                cache_key = (quality, max_width)
                cached = self.jpeg_cache.get(cache_key)
                if cached:
                    return (sequence, cached, captured_at) if include_captured_at else (sequence, cached)
                frame = self.frame.copy()
            result = self._encode_jpeg_frame(quality, frame, max_width)
            with self.lock:
                if self.frame_sequence == sequence and result:
                    # Bounded even when clients request arbitrary quality values.
                    if len(self.jpeg_cache) >= 4:
                        self.jpeg_cache.clear()
                    self.jpeg_cache[cache_key] = result
            return (sequence, result, captured_at) if include_captured_at else (sequence, result)

    def _encode_jpeg_frame(self, quality=85, frame=None, max_width=1280):
        """
        Get the latest frame encoded as JPEG
        
        Args:
            quality: JPEG compression quality (0-100)
            Higher quality = better image, optimized for single camera
            
        Returns:
            bytes or None: JPEG encoded frame or None if unavailable
        """
        if frame is None:
            frame = self.get_frame()
        if frame is not None:
            try:
                # Resize to HD quality for single camera (better quality)
                height, width = frame.shape[:2]
                if width > max_width:
                    # Limit to 1280px for HD quality without excessive bandwidth
                    frame = cv2.resize(frame, (max_width, int(height * max_width / width)))
                
                # Encode frame as JPEG with optimized settings for streaming
                encode_param = [
                    int(cv2.IMWRITE_JPEG_QUALITY), quality,
                    int(cv2.IMWRITE_JPEG_OPTIMIZE), 1,  # Optimize encoding
                    int(cv2.IMWRITE_JPEG_PROGRESSIVE), 0  # Disable progressive for speed
                ]
                ret, buffer = cv2.imencode('.jpg', frame, encode_param)
                if ret:
                    return buffer.tobytes()
            except Exception as e:
                logger.exception("Error encoding frame for %s: %s", self.camera.name, e)
                return None
        return None

    def public_status(self):
        """Return state suitable for the frontend, without endpoint details."""
        age = (time.monotonic() - self.last_frame_monotonic
               if self.last_frame_monotonic is not None else None)
        fresh = self.frame is not None and age is not None and age <= self.frame_timeout
        return {
            'state': 'reconnecting' if self.connection_state == 'online' and not fresh else self.connection_state,
            'message': self.connection_error,
            'has_frame': fresh,
            'frame_sequence': self.frame_sequence,
            'frame_age_seconds': round(age, 2) if age is not None else None,
            'worker_alive': bool(self.thread and self.thread.is_alive()),
        }


class CameraStreamManager:
    """
    Manages multiple camera streams globally
    """
    
    def __init__(self):
        self.streams = {}
        self.lock = threading.Lock()
        self.startup_delay = 0  # No delay needed for single camera system
    
    def get_stream(self, camera_id, persistent=False):
        """
        Get or create a camera stream
        
        Args:
            camera_id: ID of the camera
            
        Returns:
            CameraStream or None: Stream instance or None if camera not found
        """
        from .goat_models import IPCamera
        
        with self.lock:
            # Return existing stream if available
            if camera_id in self.streams:
                stream = self.streams[camera_id]
                if persistent:
                    stream.persistent = True
                if not stream.thread or not stream.thread.is_alive():
                    logger.warning('Restarting camera %s worker after exit', camera_id)
                    stream.is_running = False
                    stream.start()
                return stream
            
            # Create new stream
            try:
                camera = IPCamera.objects.get(id=camera_id, is_active=True)
                
                # Add delay between camera starts to prevent system overload
                if len(self.streams) > 0:
                    time.sleep(self.startup_delay)
                
                stream = CameraStream(camera)
                stream.persistent = persistent
                stream.start()
                self.streams[camera_id] = stream
                return stream
            except IPCamera.DoesNotExist:
                logger.warning("Camera with ID %s not found", camera_id)
                return None
            except Exception as e:
                logger.exception("Error creating stream for camera %s: %s", camera_id, e)
                return None
    
    def stop_stream(self, camera_id):
        """Stop a specific camera stream"""
        with self.lock:
            if camera_id in self.streams:
                self.streams[camera_id].stop()
                del self.streams[camera_id]
                return True
        return False

    def get_existing_stream(self, camera_id):
        """Return a managed stream without opening a new camera connection."""
        with self.lock:
            return self.streams.get(camera_id)
    
    def stop_all_streams(self):
        """Stop all camera streams"""
        with self.lock:
            for stream in self.streams.values():
                stream.stop()
            self.streams.clear()


# Global camera stream manager instance
camera_manager = CameraStreamManager()
