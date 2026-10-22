from io import BytesIO
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from PIL import Image, ImageDraw

from iot.goat_models import Goat, GoatImage
from iot.models import Device, SensorReading, SensorReadingSummary
from marketplace.auth import FARM_OPERATOR_GROUP_NAME, FARM_OWNER_GROUP_NAME
from security.models import PersonDetection


def mobile_test_photo(name="goat.jpg"):
    image = Image.new("RGB", (800, 600), "#6f5538")
    draw = ImageDraw.Draw(image)
    for y in range(0, 600, 50):
        for x in range(0, 800, 50):
            if (x // 50 + y // 50) % 2:
                draw.rectangle((x, y, x + 50, y + 50), fill="#e7d8b5")
    output = BytesIO()
    image.save(output, "JPEG", quality=90)
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/jpeg")


class MobileApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="mobile-owner", password="safe-test-password"
        )
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        self.user.groups.add(owner_group)

    def authenticate(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_login_reuses_django_account_and_reports_role(self):
        response = self.client.post(reverse("mobile_api:login"), {
            "username": "mobile-owner", "password": "safe-test-password"
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["role"], "farm_owner")
        self.assertTrue(response.data["user"]["permissions"]["manage_farm"])

    def test_marketplace_account_cannot_login_to_owner_app(self):
        outsider = get_user_model().objects.create_user(
            username="buyer", password="safe-test-password"
        )
        response = self.client.post(reverse("mobile_api:login"), {
            "username": outsider.username, "password": "safe-test-password"
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("token", response.data)

    def test_farm_operator_cannot_login_to_owner_app(self):
        operator = get_user_model().objects.create_user(
            username="operator", password="safe-test-password"
        )
        operator_group, _ = Group.objects.get_or_create(name=FARM_OPERATOR_GROUP_NAME)
        operator.groups.add(operator_group)
        response = self.client.post(reverse("mobile_api:login"), {
            "username": operator.username, "password": "safe-test-password"
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("token", response.data)

        token = Token.objects.create(user=operator)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(self.client.get(reverse("mobile_api:me")).status_code, 403)
        self.assertEqual(self.client.get(reverse("mobile_api:dashboard")).status_code, 403)

    def test_dashboard_requires_authentication_and_is_safe_when_empty(self):
        self.assertEqual(self.client.get(reverse("mobile_api:dashboard")).status_code, 401)
        self.authenticate()
        response = self.client.get(reverse("mobile_api:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["system"]["controller_online"])
        self.assertFalse(response.data["environment"]["online"])
        self.assertIsNone(response.data["environment"]["last_seen"])
        self.assertEqual(response.data["goats"]["registered"], 0)

    def test_environment_history_returns_bounded_dashboard_device_series(self):
        now = timezone.now()
        device = Device.objects.create(
            device_id="ENV-1", name="Environment node", device_type="sensor"
        )
        SensorReading.objects.create(
            device=device, temperature=27, humidity=70, timestamp=now
        )
        SensorReadingSummary.objects.create(
            device=device,
            sensor_type="temperature",
            unit="°C",
            period_start=now - timedelta(minutes=30),
            period_end=now,
            average_value=26.5,
            minimum_value=26,
            maximum_value=27,
            sample_count=60,
        )
        SensorReadingSummary.objects.create(
            device=device,
            sensor_type="temperature",
            unit="°C",
            period_start=now - timedelta(days=2),
            period_end=now - timedelta(days=2) + timedelta(minutes=30),
            average_value=22,
            minimum_value=21,
            maximum_value=23,
            sample_count=60,
        )
        self.authenticate()
        response = self.client.get(
            reverse("mobile_api:environment_history"), {"hours": 24}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["device"]["device_id"], "ENV-1")
        self.assertEqual(len(response.data["series"]["temperature"]), 1)
        self.assertEqual(response.data["series"]["temperature"][0]["average"], 26.5)
        self.assertEqual(response.data["series"]["humidity"], [])

    def test_environment_history_rejects_unbounded_ranges(self):
        self.authenticate()
        response = self.client.get(
            reverse("mobile_api:environment_history"), {"hours": 720}
        )
        self.assertEqual(response.status_code, 400)

    def test_report_summary_uses_all_server_records_and_bounded_security_window(self):
        Goat.objects.create(goat_id="GOAT-001", name="Luna", gender="female", health_status="healthy")
        Goat.objects.create(goat_id="GOAT-002", name="Max", gender="male", health_status="monitoring")
        Goat.objects.create(goat_id="COMMUNITY-001", gender="female", record_source=Goat.COMMUNITY)
        PersonDetection.objects.create(confidence=0.8, review_state="reviewed", status="dismissed")
        PersonDetection.objects.create(confidence=0.6, review_state="unreviewed", status="confirmed")
        PersonDetection.objects.create(
            confidence=0.2,
            detected_at=timezone.now() - timedelta(days=2),
        )
        self.authenticate()

        response = self.client.get(reverse("mobile_api:report_summary"), {"hours": 24})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["herd"]["total"], 2)
        self.assertEqual(sum(row["count"] for row in response.data["herd"]["gender"]), 2)
        self.assertEqual(response.data["security"]["total"], 2)
        self.assertEqual(response.data["security"]["reviewed"], 1)
        self.assertEqual(response.data["security"]["unreviewed"], 1)
        self.assertEqual(response.data["security"]["average_confidence"], 70.0)

    def test_report_summary_rejects_unbounded_ranges(self):
        self.authenticate()
        response = self.client.get(reverse("mobile_api:report_summary"), {"hours": 720})
        self.assertEqual(response.status_code, 400)

    def test_goat_list_filters_server_side_and_returns_smart_farm_facets(self):
        Goat.objects.create(goat_id="GOAT-001", name="Luna", gender="female")
        Goat.objects.create(
            goat_id="GOAT-002", name="Max", gender="male", status="missing"
        )
        Goat.objects.create(
            goat_id="COMMUNITY-001", gender="female", record_source=Goat.COMMUNITY
        )
        self.authenticate()
        response = self.client.get(reverse("mobile_api:goats"), {"gender": "male"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["goat_id"], "GOAT-002")
        self.assertEqual(response.data["facets"]["all"], 2)
        self.assertEqual(response.data["facets"]["female"], 1)
        self.assertEqual(response.data["facets"]["missing"], 1)

    def test_security_list_returns_server_wide_kpis(self):
        PersonDetection.objects.create(
            confidence=0.9, review_state="reviewed", status="dismissed"
        )
        PersonDetection.objects.create(confidence=0.5, review_state="unreviewed")
        self.authenticate()
        response = self.client.get(reverse("security:persondetection-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["summary"]["high_confidence"], 1)
        self.assertEqual(response.data["summary"]["reviewed"], 1)
        self.assertEqual(response.data["summary"]["unreviewed"], 1)

    def test_owner_can_create_and_update_smart_farm_goat_record(self):
        self.authenticate()
        created = self.client.post(reverse("mobile_api:goats"), {
            "goat_id": "FARM-NEW-01",
            "name": "Maya",
            "tag_number": "TAG-01",
            "breed": "boer",
            "gender": "female",
            "weight_kg": "34.5",
            "health_status": "healthy",
            "vaccination_status": "fully_vaccinated",
            "health_notes": "Clear eyes and normal appetite.",
        }, format="json")
        self.assertEqual(created.status_code, 201)
        goat = Goat.objects.get(goat_id="FARM-NEW-01")
        self.assertEqual(goat.owner, self.user)
        self.assertEqual(goat.record_source, Goat.SMART_FARM)

        updated = self.client.put(
            reverse("mobile_api:goat_detail", args=[goat.goat_id]),
            {
                "goat_id": goat.goat_id,
                "name": "Maya Updated",
                "tag_number": "TAG-01",
                "breed": "boer",
                "gender": "female",
                "date_of_birth": "",
                "color_markings": "White forehead patch",
                "health_status": "monitoring",
                "health_notes": "Observe appetite.",
                "vaccination_status": "fully_vaccinated",
                "vaccine_name": "CDT",
                "vaccination_date": "",
                "next_due_date": "",
                "notes": "Owner mobile update.",
                "weight_kg": "99",
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        goat.refresh_from_db()
        self.assertEqual(goat.name, "Maya Updated")
        self.assertEqual(goat.health_status, "monitoring")
        self.assertEqual(goat.weight_kg, 34.5)

    def test_owner_can_replace_select_and_delete_standard_goat_photos(self):
        self.authenticate()
        goat = Goat.objects.create(
            goat_id="PHOTO-01",
            name="Photo Goat",
            breed="native",
            gender="female",
            owner=self.user,
            record_source=Goat.SMART_FARM,
        )
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            uploaded = self.client.post(
                reverse("mobile_api:goat_photo_manage", args=[goat.goat_id]),
                {"angle": "front", "image": mobile_test_photo("front.jpg")},
                format="multipart",
            )
            self.assertEqual(uploaded.status_code, 201)
            first = GoatImage.objects.get(goat=goat, angle="front")
            self.assertTrue(first.is_primary)

            replaced = self.client.post(
                reverse("mobile_api:goat_photo_manage", args=[goat.goat_id]),
                {"angle": "front", "image": mobile_test_photo("replacement.jpg")},
                format="multipart",
            )
            self.assertEqual(replaced.status_code, 201)
            self.assertEqual(GoatImage.objects.filter(goat=goat, angle="front").count(), 1)

            added = self.client.post(
                reverse("mobile_api:goat_photo_manage", args=[goat.goat_id]),
                {"angle": "left", "image": mobile_test_photo("left.jpg")},
                format="multipart",
            )
            self.assertEqual(added.status_code, 201)
            left = GoatImage.objects.get(goat=goat, angle="left")
            selected = self.client.post(
                reverse("mobile_api:goat_photo_action", args=[goat.goat_id, left.pk]),
                {"action": "set_primary"},
                format="json",
            )
            self.assertEqual(selected.status_code, 200)
            left.refresh_from_db()
            self.assertTrue(left.is_primary)

            deleted = self.client.post(
                reverse("mobile_api:goat_photo_action", args=[goat.goat_id, left.pk]),
                {"action": "delete"},
                format="json",
            )
            self.assertEqual(deleted.status_code, 200)
            self.assertFalse(GoatImage.objects.filter(pk=left.pk).exists())
            first.refresh_from_db()
            self.assertTrue(first.is_primary)
    def test_goat_management_options_match_model_choices(self):
        self.authenticate()
        response = self.client.get(reverse("mobile_api:goat_options"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            {"value": "boer", "label": "Boer"},
            response.data["breeds"],
        )
        self.assertIn(
            {"value": "healthy", "label": "Healthy"},
            response.data["health_statuses"],
        )

    def test_realtime_ticket_is_scoped(self):
        self.authenticate()
        response = self.client.post(
            reverse("mobile_api:realtime_ticket"), {"purpose": "websocket"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["expires_in"], 60)

    def test_expired_mobile_token_is_rejected_and_revoked(self):
        token = Token.objects.create(user=self.user)
        Token.objects.filter(pk=token.pk).update(created=timezone.now() - timedelta(days=31))
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = self.client.get(reverse("mobile_api:dashboard"))
        self.assertEqual(response.status_code, 401)
        self.assertFalse(Token.objects.filter(pk=token.pk).exists())
