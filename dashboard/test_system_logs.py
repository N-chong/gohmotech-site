import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from marketplace.auth import FARM_OWNER_GROUP_NAME

from .models import SystemLog


class SystemLogCaptureTests(TestCase):
    def setUp(self):
        self.password = "Strong-test-password-932!"
        self.staff = get_user_model().objects.create_user(
            username="log-admin", password=self.password, is_staff=True,
        )

    def test_successful_and_failed_logins_are_recorded_without_passwords(self):
        self.assertTrue(self.client.login(username=self.staff.username, password=self.password))
        success = SystemLog.objects.get(event="auth.login_succeeded")
        self.assertEqual(success.actor, self.staff)
        self.assertEqual(success.category, SystemLog.CATEGORY_AUTH)

        self.client.logout()
        self.assertFalse(self.client.login(username=self.staff.username, password="wrong-secret"))
        failed = SystemLog.objects.get(event="auth.login_failed")
        self.assertEqual(failed.level, SystemLog.LEVEL_WARNING)
        self.assertNotIn("wrong-secret", json.dumps(failed.metadata))
        self.assertNotIn("wrong-secret", failed.message)

    def test_authenticated_mutation_is_recorded_without_request_body(self):
        owner = get_user_model().objects.create_user(
            username="audit-owner", password=self.password,
        )
        group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        owner.groups.add(group)
        self.client.force_login(owner)
        SystemLog.objects.all().delete()

        response = self.client.post(
            reverse("dashboard:tutorial_state"),
            data=json.dumps({"action": "skip", "private": "must-not-be-logged"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        entry = SystemLog.objects.get(event="request.mutation")
        self.assertEqual(entry.actor, owner)
        self.assertEqual(entry.request_method, "POST")
        self.assertEqual(entry.status_code, 200)
        self.assertNotIn("must-not-be-logged", json.dumps(entry.metadata))


class SystemLogViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user("logs-staff", password="test-pass", is_staff=True)
        self.regular = user_model.objects.create_user("logs-regular", password="test-pass")
        SystemLog.objects.create(
            level=SystemLog.LEVEL_ERROR,
            category=SystemLog.CATEGORY_SYSTEM,
            event="service.example_failed",
            message="Example service failed safely.",
            source="tests",
        )

    def test_system_logs_page_is_staff_only(self):
        self.client.force_login(self.regular)
        response = self.client.get(reverse("dashboard:system_logs"))
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard:system_logs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "service.example_failed")
        self.assertContains(response, "Administrator access only")

    def test_system_logs_can_be_filtered(self):
        SystemLog.objects.create(
            level=SystemLog.LEVEL_INFO,
            category=SystemLog.CATEGORY_AUTH,
            event="auth.unrelated",
            message="Another event",
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("dashboard:system_logs"), {
            "q": "Example service", "level": "error", "category": "system",
        })

        self.assertContains(response, "service.example_failed")
        self.assertNotContains(response, "auth.unrelated")
