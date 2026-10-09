import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import reverse

from marketplace.auth import FARM_OWNER_GROUP_NAME, FARM_OPERATOR_GROUP_NAME
from marketplace.models import SellerProfile
from .models import OnboardingProgress
from .onboarding import tutorial_role, tutorial_steps


class OnboardingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="tour-owner")
        cls.owner.groups.add(Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)[0])
        cls.seller = get_user_model().objects.create_user(username="tour-seller")
        SellerProfile.objects.create(user=cls.seller, status="approved", farm_name="Seller Farm")
        cls.buyer = get_user_model().objects.create_user(username="tour-buyer")
        cls.admin = get_user_model().objects.create_user(username="tour-admin", is_staff=True)
        cls.operator = get_user_model().objects.create_user(username="tour-operator")
        cls.operator.groups.add(Group.objects.get_or_create(name=FARM_OPERATOR_GROUP_NAME)[0])

    def setUp(self):
        self.url = reverse("dashboard:tutorial_state")
        self.client.force_login(self.owner)

    def post(self, action, **kwargs):
        return self.client.post(self.url, json.dumps({"action": action, **kwargs}), content_type="application/json")

    def test_roles_follow_existing_permissions_and_owner_precedes_seller(self):
        self.assertEqual(tutorial_role(self.owner), "farm_owner")
        self.assertEqual(tutorial_role(self.seller), "seller")
        for user in [self.buyer, self.admin, self.operator]:
            self.assertIsNone(tutorial_role(user))
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.post("replay").status_code, 403)
            self.assertFalse(OnboardingProgress.objects.filter(user=user).exists())
        for status in ["pending", "rejected", "suspended"]:
            SellerProfile.objects.filter(user=self.seller).update(status=status)
            self.client.force_login(self.seller)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_first_login_and_progress_survive_new_browser(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(response.json()["active"])
        self.assertEqual(response.json()["step"], 0)
        self.post("step", step=3)
        other_browser = Client()
        other_browser.force_login(self.owner)
        self.assertEqual(other_browser.get(self.url).json()["step"], 3)
        self.assertEqual(self.post("step", step=2).json()["step"], 2)

    def test_skip_is_permanent_account_specific_and_idempotent(self):
        self.assertFalse(self.post("skip").json()["active"])
        progress = OnboardingProgress.objects.get(user=self.owner)
        self.assertTrue(progress.has_completed_tutorial)
        self.assertEqual(progress.completion_reason, "skipped")
        completed_at = progress.completed_at
        other_browser = Client()
        other_browser.force_login(self.owner)
        self.assertFalse(other_browser.get(self.url).json()["active"])
        self.post("skip")
        progress.refresh_from_db()
        self.assertEqual(progress.completed_at, completed_at)
        self.client.force_login(self.seller)
        self.assertTrue(self.client.get(self.url).json()["active"])

    def test_finish_requires_last_step_and_persists(self):
        self.assertEqual(self.post("finish").status_code, 400)
        steps = self.client.get(self.url).json()["steps"]
        self.post("step", step=len(steps) - 1)
        self.assertTrue(self.post("finish").json()["completed"])
        self.assertEqual(OnboardingProgress.objects.get(user=self.owner).completion_reason, "finished")
        self.client.logout()
        self.client.force_login(self.owner)
        self.assertFalse(self.client.get(self.url).json()["active"])

    def test_replay_preserves_completion_and_resumes_across_pages(self):
        self.post("skip")
        self.assertTrue(self.post("replay").json()["active"])
        self.post("step", step=3)
        state = self.client.get(self.url).json()
        self.assertTrue(state["completed"])
        self.assertEqual(state["step"], 3)
        other_browser = Client()
        other_browser.force_login(self.owner)
        self.assertFalse(other_browser.get(self.url).json()["active"])
        self.post("step", step=len(state["steps"]) - 1)
        self.assertFalse(self.post("finish").json()["active"])
        self.assertEqual(OnboardingProgress.objects.get(user=self.owner).completion_reason, "skipped")

    def test_stale_tab_cannot_reopen_completed_tutorial(self):
        other_browser = Client()
        other_browser.force_login(self.owner)
        other_browser.get(self.url)
        self.post("skip")
        response = other_browser.post(self.url, json.dumps({"action": "step", "step": 1}), content_type="application/json")
        self.assertFalse(response.json()["active"])

    def test_malformed_requests_and_csrf(self):
        for data in ["{", "null", "[]", '{"action":[]}', '{"action":{}}', '{"action":"delete"}', '{"action":"step","step":true}', '{"action":"step","step":-1}', '{"action":"step","step":500}']:
            self.assertEqual(self.client.post(self.url, data, content_type="application/json").status_code, 400)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.owner)
        self.assertEqual(protected.post(self.url, '{"action":"skip"}', content_type="application/json").status_code, 403)
        self.assertFalse(OnboardingProgress.objects.filter(user=self.owner, has_completed_tutorial=True).exists())
        protected.get(reverse("iot:owner_dashboard"))
        token = protected.cookies["csrftoken"].value
        self.assertEqual(protected.post(self.url, '{"action":"skip"}', content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_role_change_does_not_erase_completion(self):
        self.client.force_login(self.seller)
        self.post("skip")
        self.seller.groups.add(Group.objects.get(name=FARM_OWNER_GROUP_NAME))
        state = self.client.get(self.url).json()
        self.assertEqual(state["role"], "farm_owner")
        self.assertFalse(state["active"])
        self.assertEqual(self.post("replay").json()["step"], 0)

    def test_real_tour_pages_render_for_each_role(self):
        for user, role in [(self.owner, "farm_owner"), (self.seller, "seller")]:
            self.client.force_login(user)
            for url in {step["url"] for step in tutorial_steps(role)}:
                with self.subTest(role=role, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'id="onboarding-config"')
                    self.assertContains(response, "data-onboarding-replay")
            if role == "seller":
                self.assertTrue(all(step["url"].startswith("/marketplace/") for step in tutorial_steps(role)))

    def test_widget_hidden_for_other_roles(self):
        for user in [self.buyer, self.admin, self.operator]:
            self.client.force_login(user)
            response = self.client.get(reverse("marketplace:list"))
            self.assertNotContains(response, 'id="onboarding-config"')
            self.assertNotContains(response, "data-onboarding-replay")
