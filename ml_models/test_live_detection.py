import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from .live_detection import demand, key, status
from .views import live_detection_control


class ManualDetectionDemandTests(SimpleTestCase):
    def setUp(self):
        self.client = Mock()
        self.next_start = datetime(2026, 10, 13, 7, tzinfo=timezone.utc)
        self.schedule = patch(
            "ml_models.live_detection.schedule_window",
            return_value=(False, None, self.next_start),
        )
        self.schedule.start()
        self.addCleanup(self.schedule.stop)

    def test_orphaned_manual_session_is_cleared(self):
        self.client.zcard.return_value = 0
        self.client.get.return_value = "1"  # Legacy manual latch.
        self.client.zscore.return_value = None

        mode, viewers, _ = demand(1, client=self.client)

        self.assertEqual((mode, viewers), ("Inactive", 0))
        self.client.delete.assert_called_once_with(key(1, "manual"))

    def test_manual_mode_requires_its_own_active_viewer(self):
        token = "11111111-1111-4111-8111-111111111111"
        self.client.zcard.return_value = 1
        self.client.get.return_value = token
        self.client.zscore.return_value = 1234
        self.client.exists.side_effect = lambda name: name == key(1, "manual")
        self.client.hgetall.return_value = {}

        state = status(1, client=self.client)

        self.assertEqual(state["mode"], "Manual")
        self.assertTrue(state["manual_enabled"])
        self.client.delete.assert_not_called()

    def test_another_viewer_does_not_keep_manual_session_alive(self):
        self.client.zcard.return_value = 1
        self.client.get.return_value = "11111111-1111-4111-8111-111111111111"
        self.client.zscore.return_value = None

        mode, viewers, _ = demand(1, client=self.client)

        self.assertEqual((mode, viewers), ("Live Viewing", 1))
        self.client.delete.assert_called_once_with(key(1, "manual"))

    @patch("ml_models.views.IPCamera")
    @patch("ml_models.live_detection.redis_client")
    @patch("ml_models.live_detection.viewer_heartbeat")
    @patch("ml_models.live_detection.status", return_value={"mode": "Manual"})
    def test_manual_start_is_tied_to_requesting_viewer(self, _status, heartbeat, redis, camera):
        token = "11111111-1111-4111-8111-111111111111"
        camera.objects.filter.return_value.first.return_value = SimpleNamespace(id=1)
        request = RequestFactory().post(
            "/ml/api/live-detection/",
            data=json.dumps({"action": "manual_start", "token": token}),
            content_type="application/json",
        )
        request.user = SimpleNamespace(is_authenticated=True, is_staff=True, is_active=True)

        response = live_detection_control(request)

        self.assertEqual(response.status_code, 200)
        heartbeat.assert_called_once_with(1, token, redis.return_value)
        redis.return_value.set.assert_called_once_with(key(1, "manual"), token)
