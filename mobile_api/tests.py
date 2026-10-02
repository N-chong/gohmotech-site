from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from iot.goat_models import Goat
from marketplace.auth import FARM_OWNER_GROUP_NAME


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

    def test_marketplace_only_account_cannot_use_mobile_farm_login(self):
        outsider = get_user_model().objects.create_user(
            username="buyer", password="safe-test-password"
        )
        response = self.client.post(reverse("mobile_api:login"), {
            "username": outsider.username, "password": "safe-test-password"
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_dashboard_requires_authentication_and_is_safe_when_empty(self):
        self.assertEqual(self.client.get(reverse("mobile_api:dashboard")).status_code, 401)
        self.authenticate()
        response = self.client.get(reverse("mobile_api:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["system"]["controller_online"])
        self.assertEqual(response.data["goats"]["registered"], 0)

    def test_goat_list_exposes_smart_farm_inventory(self):
        Goat.objects.create(goat_id="GOAT-001", name="Luna", gender="female")
        self.authenticate()
        response = self.client.get(reverse("mobile_api:goats"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["goat_id"], "GOAT-001")

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
