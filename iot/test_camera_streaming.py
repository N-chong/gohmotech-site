from unittest.mock import patch
import asyncio
import time

import numpy as np
from django.test import SimpleTestCase

from .admin import IPCameraAdminForm
from .camera_utils import CameraStream, describe_stream_url
from .goat_models import IPCamera
from .views import generate_mjpeg_stream, generate_mjpeg_stream_async


class FakeCamera:
    name = "Barn camera"
    camera_type = "rtsp"
    rtsp_url = "rtsp://operator:top-secret@21.1.1.20:554/stream?token=hidden"
    status = "inactive"

    def __init__(self):
        self.online_calls = 0
        self.offline_messages = []

    def get_stream_url(self):
        return self.rtsp_url

    def mark_online(self):
        self.status = "active"
        self.online_calls += 1

    def mark_offline(self, message=""):
        self.status = "error"
        self.offline_messages.append(message)


class FakeCapture:
    def __init__(self, *args):
        self.args = args
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        return True, np.zeros((48, 64, 3), dtype=np.uint8)

    def set(self, *args):
        return True

    def getBackendName(self):
        return "FFMPEG"

    def release(self):
        self.released = True


class CameraStreamTests(SimpleTestCase):
    def test_idle_unpinned_stream_releases_capture(self):
        stream = CameraStream(FakeCamera())
        capture = FakeCapture()
        stream.capture = capture
        stream.is_running = True
        stream.last_consumer_at = time.monotonic() - stream.idle_timeout - 1

        stream._update_frame()

        self.assertFalse(stream.is_running)
        self.assertTrue(stream.stop_event.is_set())
        self.assertTrue(capture.released)

    def test_configured_stream_url_follows_mac_resolved_dhcp_address(self):
        camera = IPCamera(
            camera_id="CAM-1",
            name="Barn camera",
            camera_type="rtsp",
            mac_address="00:13:00:94:E6:EA",
            ip_address="10.42.0.195",
            port=554,
            rtsp_url=(
                "rtsp://operator:top-secret@10.42.0.195:554/"
                "user=admin_password=_channel=0_stream=0&onvif=0.sdp"
            ),
            location="Barn",
            # A hard power cut leaves this value active in the database.  It
            # must not suppress address discovery on the next boot.
            status="active",
        )

        with patch.object(camera, "resolve_ip_from_mac", return_value="10.42.0.27"), \
                patch.object(camera, "save"):
            stream_url = camera.get_stream_url()

        self.assertEqual(camera.ip_address, "10.42.0.27")
        self.assertEqual(
            stream_url,
            "rtsp://operator:top-secret@10.42.0.27:554/"
            "user=admin_password=_channel=0_stream=0&onvif=0.sdp",
        )

    @patch("iot.camera_utils.cv2.VideoCapture", side_effect=FakeCapture)
    def test_each_connect_refreshes_endpoint_before_opening(self, video_capture):
        camera = FakeCamera()
        camera.refresh_from_db = lambda: setattr(
            camera, "rtsp_url", "rtsp://operator:top-secret@21.1.1.21:554/stream"
        )
        stream = CameraStream(camera)

        self.assertTrue(stream._connect())

        self.assertEqual(video_capture.call_args.args[0], camera.rtsp_url)
        self.assertEqual(stream.stream_url, camera.rtsp_url)

    def test_endpoint_description_never_contains_credentials_or_query(self):
        description = describe_stream_url(
            "rtsp://operator:top-secret@21.1.1.20:554/stream?token=hidden"
        )

        self.assertEqual(description, "rtsp://21.1.1.20:554/stream")
        self.assertNotIn("operator", description)
        self.assertNotIn("top-secret", description)
        self.assertNotIn("token", description)

    @patch("iot.camera_utils.cv2.VideoCapture", side_effect=FakeCapture)
    def test_connect_uses_ffmpeg_timeouts_and_records_first_frame(self, video_capture):
        camera = FakeCamera()
        stream = CameraStream(camera)

        self.assertTrue(stream._connect())

        args = video_capture.call_args.args
        self.assertEqual(args[0], camera.rtsp_url)
        self.assertEqual(args[1], 1900)  # cv2.CAP_FFMPEG
        self.assertIn(8000, args[2])
        self.assertEqual(stream.connection_state, "online")
        self.assertTrue(stream.public_status()["has_frame"])
        self.assertEqual(camera.online_calls, 1)

    @patch("iot.camera_utils.cv2.VideoCapture")
    def test_connect_failure_has_safe_public_error(self, video_capture):
        video_capture.return_value.isOpened.return_value = False
        camera = FakeCamera()
        stream = CameraStream(camera)

        self.assertFalse(stream._connect())

        status = stream.public_status()
        self.assertEqual(status["state"], "unavailable")
        self.assertNotIn("top-secret", status["message"])
        self.assertEqual(camera.offline_messages, ["Unable to open the camera stream."])

    def test_wsgi_and_asgi_stream_iterators_match_the_server_protocol(self):
        stream = type("Stream", (), {"get_jpeg_frame": lambda self, **kwargs: None})()

        self.assertTrue(hasattr(generate_mjpeg_stream(stream, 1), "__next__"))
        self.assertTrue(hasattr(generate_mjpeg_stream_async(stream, 1), "__anext__"))

    def test_stale_frames_are_not_delivered_or_reported_live(self):
        stream = CameraStream(FakeCamera())
        stream._publish_frame(np.zeros((48, 64, 3), dtype=np.uint8))
        stream.connection_state = 'online'
        self.assertTrue(stream.get_jpeg_frame())
        stream.last_frame_monotonic -= stream.frame_timeout + 1
        self.assertIsNone(stream.get_frame())
        self.assertIsNone(stream.get_jpeg_frame())
        self.assertFalse(stream.public_status()['has_frame'])
        self.assertEqual(stream.public_status()['state'], 'reconnecting')

    def test_mobile_encoding_preserves_source_and_snapshot_resolution(self):
        import cv2
        stream = CameraStream(FakeCamera())
        stream._publish_frame(np.zeros((720, 1280, 3), dtype=np.uint8))
        _, mobile = stream.get_jpeg_packet(75, max_width=640)
        snapshot = stream.get_jpeg_frame(95)
        self.assertEqual(cv2.imdecode(np.frombuffer(mobile, np.uint8), 1).shape[:2], (360, 640))
        self.assertEqual(cv2.imdecode(np.frombuffer(snapshot, np.uint8), 1).shape[:2], (720, 1280))
        self.assertEqual(stream.get_frame().shape[:2], (720, 1280))

    def test_capture_timestamp_is_preserved_across_encoding_and_cache_hits(self):
        stream = CameraStream(FakeCamera())
        stream._publish_frame(np.zeros((48, 64, 3), dtype=np.uint8))
        captured = stream.last_frame_time
        first = stream.get_jpeg_packet(50, max_width=320, include_captured_at=True)
        self.assertEqual(first[2], captured)
        self.assertEqual(first, stream.get_jpeg_packet(50, max_width=320, include_captured_at=True))
        self.assertEqual(stream.get_jpeg_packet(50, max_width=320), first[:2])
        stream.last_frame_monotonic -= stream.frame_timeout + 1
        self.assertEqual(stream.get_jpeg_packet(50, max_width=320, include_captured_at=True), (1, None, captured))

    def test_default_preview_is_bounded_but_explicit_high_quality_still_works(self):
        from django.test import RequestFactory
        from .views import camera_feed
        stream = CameraStream(FakeCamera())
        stream._publish_frame(np.zeros((720, 1280, 3), dtype=np.uint8))
        request = RequestFactory().get('/iot/camera/feed/1/')
        with patch('iot.views.get_object_or_404'), patch('iot.views.camera_manager.get_stream', return_value=stream):
            # Exercise the view without changing the existing permission decorators.
            response = camera_feed.__wrapped__.__wrapped__(request, 1)
            part = next(iter(response.streaming_content))
            self.assertIn(b'X-Frame-Captured-At:', part)
            self.assertIn('X-Stream-Started-At', response)
            start = part.index(b'\r\n\r\n') + 4
            import cv2
            jpeg = cv2.imdecode(np.frombuffer(part[start:-2], np.uint8), 1)
            self.assertEqual(jpeg.shape[:2], (180, 320))
            response.close()
            request = RequestFactory().get('/iot/camera/feed/1/?width=1280&quality=95&fps=10')
            response = camera_feed.__wrapped__.__wrapped__(request, 1)
            part = next(iter(response.streaming_content))
            start = part.index(b'\r\n\r\n') + 4
            jpeg = cv2.imdecode(np.frombuffer(part[start:-2], np.uint8), 1)
            self.assertEqual(jpeg.shape[:2], (720, 1280))
            response.close()

    @patch('iot.camera_utils.cv2.VideoCapture', side_effect=FakeCapture)
    def test_database_status_failure_does_not_stop_capture(self, capture):
        camera = FakeCamera()
        camera.mark_online = lambda: (_ for _ in ()).throw(RuntimeError('DB unavailable'))
        stream = CameraStream(camera)
        self.assertTrue(stream._connect())
        self.assertTrue(stream.public_status()['has_frame'])

    @patch('iot.camera_utils.cv2.imencode', wraps=__import__('cv2').imencode)
    def test_viewers_share_encoding_and_new_frames_invalidate_cache(self, encode):
        stream = CameraStream(FakeCamera())
        stream._publish_frame(np.zeros((48, 64, 3), dtype=np.uint8))
        first = stream.get_jpeg_packet(75)
        self.assertEqual(first, stream.get_jpeg_packet(75))
        self.assertEqual(encode.call_count, 1)
        stream._publish_frame(np.ones((48, 64, 3), dtype=np.uint8))
        self.assertGreater(stream.get_jpeg_packet(75)[0], first[0])
        self.assertEqual(encode.call_count, 2)

    def test_async_stream_delivers_new_sequences_and_cleans_up(self):
        async def exercise():
            stream = CameraStream(FakeCamera())
            stream._publish_frame(np.zeros((48, 64, 3), dtype=np.uint8))
            iterator = generate_mjpeg_stream_async(stream, 1, fps=25)
            first = await anext(iterator)
            stream._publish_frame(np.ones((48, 64, 3), dtype=np.uint8))
            second = await anext(iterator)
            self.assertIn(b'X-Frame-Sequence: 1', first)
            self.assertIn(b'X-Frame-Sequence: 2', second)
            self.assertIn(b'Content-Length:', first)
            await iterator.aclose()
        asyncio.run(exercise())

    def test_sse_is_valid_text_transport_with_shared_jpeg_and_capture_time(self):
        import base64
        import json
        stream = CameraStream(FakeCamera())
        stream._publish_frame(np.zeros((48, 64, 3), dtype=np.uint8))
        captured = stream.last_frame_time
        iterator = generate_mjpeg_stream(stream, 1, quality=50, max_width=320, transport='sse')
        self.assertEqual(next(iterator), b': camera stream\n\n')
        event = next(iterator)
        self.assertTrue(event.endswith(b'\n\n'))
        self.assertIn(b'event: frame\nid: 1\n', event)
        data = next(line[6:] for line in event.splitlines() if line.startswith(b'data: '))
        packet = json.loads(data)
        self.assertEqual(packet['sequence'], 1)
        self.assertEqual(packet['captured_at'], captured)
        self.assertEqual(base64.b64decode(packet['jpeg']), stream.get_jpeg_packet(50, max_width=320)[1])
        iterator.close()

    def test_finite_jpeg_returns_one_current_frame_and_never_waits_for_capture(self):
        import cv2
        from django.test import RequestFactory
        from .views import camera_feed
        stream = CameraStream(FakeCamera())
        stream._publish_frame(np.zeros((720, 1280, 3), dtype=np.uint8))
        request = RequestFactory().get('/iot/camera/feed/1/?transport=jpeg')
        with patch('iot.views.get_object_or_404'), patch('iot.views.camera_manager.get_stream', return_value=stream):
            response = camera_feed.__wrapped__.__wrapped__(request, 1)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.streaming)
            self.assertEqual(response['Content-Type'], 'image/jpeg')
            self.assertEqual(response['X-Frame-Sequence'], '1')
            self.assertAlmostEqual(float(response['X-Frame-Captured-At']), stream.last_frame_time, places=5)
            self.assertEqual(cv2.imdecode(np.frombuffer(response.content, np.uint8), 1).shape[:2], (180, 320))
            self.assertIn('no-store', response['Cache-Control'])
            stream._invalidate_frame()
            response = camera_feed.__wrapped__.__wrapped__(request, 1)
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')

    def test_all_camera_transports_still_require_authentication(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        from .views import camera_feed
        with patch('iot.views.camera_manager.get_stream') as get_stream:
            for transport in ['jpeg', 'sse', 'mjpeg']:
                request = RequestFactory().get('/iot/camera/feed/1/?transport=' + transport)
                request.user = AnonymousUser()
                self.assertEqual(camera_feed(request, 1).status_code, 302)
            get_stream.assert_not_called()

    def test_sse_async_iterator_and_content_type_remain_opt_in(self):
        from django.test import RequestFactory
        from .views import camera_feed
        import json
        async def exercise():
            stream = CameraStream(FakeCamera())
            stream._publish_frame(np.zeros((48, 64, 3), dtype=np.uint8))
            iterator = generate_mjpeg_stream_async(stream, 1, fps=25, transport='sse')
            self.assertEqual(await anext(iterator), b': camera stream\n\n')
            first = await anext(iterator)
            stream._publish_frame(np.ones((48, 64, 3), dtype=np.uint8))
            second = await anext(iterator)
            self.assertEqual(json.loads(next(line[6:] for line in first.splitlines() if line.startswith(b'data: ')))['sequence'], 1)
            self.assertEqual(json.loads(next(line[6:] for line in second.splitlines() if line.startswith(b'data: ')))['sequence'], 2)
            await iterator.aclose()
            request = RequestFactory().get('/iot/camera/feed/1/?transport=sse')
            with patch('iot.views.get_object_or_404'), patch('iot.views.camera_manager.get_stream', return_value=stream):
                response = camera_feed.__wrapped__.__wrapped__(request, 1)
                self.assertEqual(response['Content-Type'], 'text/event-stream')
                self.assertIn('no-store', response['Cache-Control'])
                response.close()
        asyncio.run(exercise())

    def test_capture_recovers_after_temporary_read_failure(self):
        class RecoveringCapture(FakeCapture):
            attempts = 0

            def __init__(self, *args):
                super().__init__(*args)
                type(self).attempts += 1
                self.first = type(self).attempts == 1

            def grab(self):
                time.sleep(0.005)
                return not self.first

            def retrieve(self):
                return (False, None) if self.first else self.read()

        with patch('iot.camera_utils.cv2.VideoCapture', RecoveringCapture):
            stream = CameraStream(FakeCamera())
            stream.frame_timeout = 0.03
            stream.start()
            deadline = time.monotonic() + 2
            try:
                while time.monotonic() < deadline:
                    if RecoveringCapture.attempts >= 2 and stream.public_status()['has_frame']:
                        break
                    time.sleep(0.01)
                self.assertGreaterEqual(RecoveringCapture.attempts, 2)
                self.assertTrue(stream.public_status()['has_frame'])
                self.assertEqual(stream.connection_state, 'online')
            finally:
                stream.stop()
            self.assertFalse(stream.thread.is_alive())

    def test_admin_form_does_not_render_stored_camera_secrets(self):
        camera = IPCamera(
            pk=1,
            camera_id="CAM-1",
            name="Barn camera",
            camera_type="rtsp",
            ip_address="21.1.1.20",
            port=554,
            username="operator",
            password="top-secret",
            rtsp_url="rtsp://operator:top-secret@21.1.1.20:554/stream",
            location="Barn",
        )

        form = IPCameraAdminForm(instance=camera)
        rendered_secrets = "".join(
            str(form[name])
            for name in ("username", "password", "rtsp_url", "http_url", "snapshot_url")
        )

        self.assertNotIn("operator", rendered_secrets)
        self.assertNotIn("top-secret", rendered_secrets)
        self.assertNotIn("rtsp://", rendered_secrets)
        self.assertIn("Saved (hidden)", form.fields["password"].help_text)
        self.assertIn("Saved (hidden)", form.fields["rtsp_url"].help_text)
        self.assertEqual(form.fields["http_url"].help_text, "No value saved.")
