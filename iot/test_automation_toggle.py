import json
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from marketplace.auth import FARM_OWNER_GROUP_NAME


@override_settings(
    CSRF_COOKIE_NAME="custom_production_csrf",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "automation-toggle-tests",
        }
    },
)
class AutomationToggleCsrfTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.owner = get_user_model().objects.create_user(
            "automation-owner", password="test-password"
        )
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        self.owner.groups.add(owner_group)
        self.client.force_login(self.owner)
        cache.clear()

    def _rendered_csrf_token(self, response):
        match = re.search(
            rb'name="csrfmiddlewaretoken" value="([^"]+)"', response.content
        )
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def test_control_page_toggle_works_with_custom_csrf_cookie_name(self):
        page = self.client.get(reverse("iot:automation_control"))
        self.assertEqual(page.status_code, 200)
        self.assertIn("custom_production_csrf", self.client.cookies)
        self.assertNotIn("csrftoken", self.client.cookies)

        response = self.client.post(
            reverse("iot:api_toggle_automation"),
            data=json.dumps({"enabled": False}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._rendered_csrf_token(page),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])
        self.assertIs(cache.get("automation_enabled"), False)

    def test_schedule_page_renders_a_csrf_token_for_fetch_requests(self):
        page = self.client.get(reverse("iot:automation_schedule"))

        self.assertEqual(page.status_code, 200)
        self.assertTrue(self._rendered_csrf_token(page))
        self.assertContains(page, "automationScheduleCsrfForm")
