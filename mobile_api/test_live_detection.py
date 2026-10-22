from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from marketplace.auth import FARM_OWNER_GROUP_NAME


class MobileLiveDetectionTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="mobile-detection-owner", password="test-password"
        )
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        self.user.groups.add(owner_group)
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.camera = SimpleNamespace(
            id=7,
            camera_id="CAM-7",
            name="Goat House",
            location="Main pen",
            detection_interval_seconds=5,
            save=Mock(),
        )
        self.status = {
            "mode": "Live Viewing",
            "running": True,
            "viewers": 1,
            "manual_enabled": False,
            "next_scheduled_at": "2026-10-17T11:00:00+08:00",
            "latest": None,
        }

    @patch("ml_models.live_detection.status")
    @patch("ml_models.live_detection.redis_client")
    @patch("mobile_api.views.LiveDetectionView._camera")
    def test_status_uses_mobile_token_authentication(self, camera, redis_client, status):
        camera.return_value = self.camera
        status.return_value = dict(self.status)

        response = self.client.get(reverse("mobile_api:live_detection"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["mode"], "Live Viewing")
        self.assertEqual(response.data["camera"]["camera_id"], "CAM-7")
        status.assert_called_once_with(self.camera.id, redis_client.return_value)

    @patch("ml_models.live_detection.status")
    @patch("ml_models.live_detection.viewer_heartbeat")
    @patch("ml_models.live_detection.redis_client")
    @patch("mobile_api.views.LiveDetectionView._camera")
    def test_owner_can_start_manual_detection_for_own_viewer(
        self, camera, redis_client, heartbeat, status
    ):
        camera.return_value = self.camera
        status.return_value = dict(self.status, mode="Manual", manual_enabled=True)
        viewer = "11111111-1111-4111-8111-111111111111"

        response = self.client.post(
            reverse("mobile_api:live_detection"),
            {"action": "manual_start", "token": viewer},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        heartbeat.assert_called_once_with(self.camera.id, viewer, redis_client.return_value)
        redis_client.return_value.set.assert_called_once()
