from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from marketplace.auth import FARM_OPERATOR_GROUP_NAME, FARM_OWNER_GROUP_NAME
from marketplace.models import Conversation, MarketplaceListing, Message

from .models import Goat


class FarmRoleAccessTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            "rbac-admin", password="test-password", is_staff=True
        )
        self.owner = User.objects.create_user("rbac-owner", password="test-password")
        self.operator = User.objects.create_user("rbac-operator", password="test-password")
        self.market_user = User.objects.create_user("rbac-market", password="test-password")
        self.owner.groups.add(Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)[0])
        self.operator.groups.add(Group.objects.get_or_create(name=FARM_OPERATOR_GROUP_NAME)[0])

    def assert_get_status(self, user, paths, expected):
        self.client.force_login(user)
        for path in paths:
            with self.subTest(user=user.username, path=path):
                self.assertEqual(self.client.get(path).status_code, expected)
        self.client.logout()

    def test_admin_can_access_system_and_operational_pages(self):
        self.assert_get_status(
            self.admin,
            ["/iot/", "/iot/automation/", "/security/", "/analytics/", "/sms/"],
            200,
        )

    def test_owner_can_operate_farm_but_not_system_administration(self):
        self.assert_get_status(
            self.owner,
            ["/iot/owner/", "/iot/monitoring/", "/iot/automation/", "/security/", "/analytics/", "/iot/devices/"],
            200,
        )
        self.assert_get_status(
            self.owner,
            ["/sms/", "/marketplace/manage/", "/ml/models/"],
            403,
        )

    def test_owner_navigation_is_grouped_and_keeps_key_features_accessible(self):
        self.client.force_login(self.owner)
        response = self.client.get("/iot/owner/")
        self.assertContains(response, ">Farm<")
        self.assertContains(response, ">Monitoring<")
        self.assertContains(response, ">Records<")
        self.assertContains(response, ">Device Status<")
        self.assertContains(response, ">Help &amp; Settings<")
        self.assertContains(response, reverse("feeding:dashboard"))
        self.assertContains(response, reverse("ml_models:detection_feed"))
        self.assertContains(response, reverse("analytics:dashboard"))

    def test_operator_can_only_open_monitoring_pages(self):
        self.assert_get_status(
            self.operator,
            ["/iot/owner/", "/iot/monitoring/", "/iot/inventory/", "/iot/tracking/", "/ml/detection/"],
            200,
        )
        self.assert_get_status(
            self.operator,
            [
                "/iot/automation/", "/iot/alerts/", "/security/", "/analytics/",
                "/iot/devices/", "/marketplace/manage/", "/marketplace/seller/dashboard/",
            ],
            403,
        )

    def test_operator_pages_hide_write_and_configuration_controls(self):
        self.client.force_login(self.operator)
        dashboard = self.client.get("/iot/owner/")
        inventory = self.client.get("/iot/inventory/")
        detection = self.client.get("/ml/detection/")
        self.assertNotContains(dashboard, "Save Schedule")
        self.assertNotContains(dashboard, "View Alerts")
        self.assertContains(inventory, "Read-only inventory")
        self.assertNotContains(detection, "Camera settings")
        self.assertNotContains(detection, 'id="camera-pass"')
        self.assertContains(detection, "Read-only live camera")

    def test_owner_and_operator_see_shared_3d_goat_house_without_dashboard_controls(self):
        for user in (self.owner, self.operator):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                dashboard = self.client.get("/iot/owner/")
                self.assertEqual(dashboard.status_code, 200)
                self.assertContains(dashboard, "3D Bahay ng Kambing")
                self.assertContains(dashboard, 'id="canvas-container-3d"')
                self.assertNotContains(dashboard, "barn-control-btn")
                self.client.logout()

    def test_owner_has_scoped_marketplace_management_without_admin_access(self):
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("marketplace:seller_dashboard")).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("marketplace:seller_listings")).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("marketplace:admin_dashboard")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("marketplace:seller_reservations")).status_code,
            200,
        )

    def test_owner_can_list_and_manage_admin_registered_smart_farm_goats(self):
        admin_goat = Goat.objects.create(
            goat_id="ADMIN-FARM-001",
            name="Admin Farm Goat",
            breed="native",
            gender="female",
            owner=self.admin,
            record_source=Goat.SMART_FARM,
        )
        admin_listing = MarketplaceListing.objects.create(
            goat=admin_goat,
            seller=self.admin,
            price="12500.00",
            sales_description="Admin-created farm listing.",
        )
        unlisted_admin_goat = Goat.objects.create(
            goat_id="ADMIN-FARM-002",
            name="Available Farm Goat",
            breed="boer",
            gender="male",
            owner=self.admin,
            record_source=Goat.SMART_FARM,
        )
        community_goat = Goat.all_objects.create(
            goat_id="PRIVATE-COMMUNITY-001",
            name="Private Community Goat",
            breed="native",
            gender="female",
            owner=self.market_user,
            record_source=Goat.COMMUNITY,
        )
        MarketplaceListing.objects.create(
            goat=community_goat,
            seller=self.market_user,
            price="9000.00",
            sales_description="Private community listing.",
        )

        self.client.force_login(self.owner)
        listings = self.client.get(reverse("marketplace:seller_listings"))
        self.assertContains(listings, admin_goat.goat_id)
        self.assertNotContains(listings, community_goat.goat_id)
        self.assertEqual(
            self.client.get(
                reverse("marketplace:seller_listing_edit", args=[admin_listing.pk])
            ).status_code,
            200,
        )

        add_page = self.client.get(reverse("marketplace:seller_listing_add"))
        self.assertContains(add_page, unlisted_admin_goat.goat_id)
        response = self.client.post(
            reverse("marketplace:seller_listing_add"),
            {
                "goat": unlisted_admin_goat.pk,
                "price": "15000.00",
                "sales_description": "Listed by the Farm Owner.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            MarketplaceListing.objects.filter(
                goat=unlisted_admin_goat,
                seller=self.owner,
            ).exists()
        )

    def test_owner_can_reply_to_admin_smart_farm_listing_conversation(self):
        admin_goat = Goat.objects.create(
            goat_id="ADMIN-FARM-MESSAGE-001",
            name="Shared Farm Goat",
            breed="native",
            gender="female",
            owner=self.admin,
            record_source=Goat.SMART_FARM,
        )
        listing = MarketplaceListing.objects.create(
            goat=admin_goat,
            seller=self.admin,
            price="12500.00",
            sales_description="Admin-created farm listing.",
        )
        conversation = Conversation.objects.create(
            listing=listing,
            buyer=self.market_user,
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("marketplace:conversation", args=[conversation.pk]),
            {"body": "This listing is still available."},
        )

        self.assertRedirects(
            response,
            reverse("marketplace:conversation", args=[conversation.pk]),
        )
        self.assertTrue(
            Message.objects.filter(
                conversation=conversation,
                sender=self.owner,
                body="This listing is still available.",
            ).exists()
        )

    def test_operator_direct_goat_add_is_forbidden_and_creates_nothing(self):
        self.client.force_login(self.operator)
        response = self.client.post(
            reverse("iot:add_goat"),
            {"goat_id": "DENIED-001", "gender": "female"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Goat.objects.filter(goat_id="DENIED-001").exists())

    def test_operator_unsafe_api_requests_are_forbidden(self):
        self.client.force_login(self.operator)
        for path in (
            "/iot/api/automation-rules/",
            "/feeding/api/schedules/",
            "/analytics/api/reports/",
            "/ml/api/detections/",
            "/security/api/notifications/",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    self.client.post(path, data={}, content_type="application/json").status_code,
                    403,
                )

    def test_owner_can_add_goat(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("iot:add_goat"),
            {
                "goat_id": "OWNER-001",
                "name": "Owner Goat",
                "breed": "native",
                "gender": "female",
                "health_status": "healthy",
                "vaccination_status": "unknown",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Goat.objects.filter(goat_id="OWNER-001", owner=self.owner).exists())

    def test_admin_can_assign_owner_and_operator_roles(self):
        self.client.force_login(self.admin)
        action_url = reverse(
            "marketplace:registered_user_action_admin", args=[self.market_user.pk]
        )
        response = self.client.post(
            action_url, {"action": "assign_role", "role": "farm_owner"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            self.market_user.groups.filter(name=FARM_OWNER_GROUP_NAME).exists()
        )
        response = self.client.post(
            action_url, {"action": "assign_role", "role": "farm_operator"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            self.market_user.groups.filter(name=FARM_OWNER_GROUP_NAME).exists()
        )
        self.assertTrue(
            self.market_user.groups.filter(name=FARM_OPERATOR_GROUP_NAME).exists()
        )

    def test_operator_cannot_assign_roles_by_posting_admin_url(self):
        self.client.force_login(self.operator)
        response = self.client.post(
            reverse(
                "marketplace:registered_user_action_admin",
                args=[self.market_user.pk],
            ),
            {"action": "assign_role", "role": "farm_owner"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            self.market_user.groups.filter(name=FARM_OWNER_GROUP_NAME).exists()
        )
