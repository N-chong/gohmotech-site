from datetime import timedelta
from decimal import Decimal
import base64
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from allauth.account.signals import user_signed_up
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from PIL import Image

from iot.models import Goat, GoatImage
from security.models import Notification as SecurityNotification
from sms.models import SmsLog

from .models import (
    Conversation,
    Favorite,
    MarketplaceListing,
    MarketplaceNotification,
    MarketplaceReport,
    Message,
    Reservation,
    SellerProfile,
    SupportMessage,
    SupportTicket,
    UserAccountState,
)
from .notification_services import create_marketplace_notification
from .services import (
    accept_reservation,
    cancel_reservation,
    complete_sale,
    confirm_pickup,
    expire_due_reservations,
    reject_reservation,
    request_pickup,
    request_reservation,
    suggest_pickup,
)
from .image_utils import optimize_marketplace_image
from .auth import (
    BUYER_GROUP_NAME,
    FARM_OWNER_GROUP_NAME,
    FARM_OPERATOR_GROUP_NAME,
    has_farm_access,
    is_approved_seller,
)


class UserManagementAndSupportSecurityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            "support-admin",
            email="admin@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            "support-customer",
            first_name="Support",
            last_name="Customer",
            email="customer@example.com",
            password="testpass123",
        )
        self.other = User.objects.create_user(
            "support-other",
            email="other@example.com",
            password="testpass123",
        )

    def create_ticket(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("marketplace:support_ticket_create"),
            {
                "subject": "Cannot update my marketplace profile",
                "category": SupportTicket.ACCOUNT,
                "description": "The profile form returns an error.",
            },
        )
        ticket = SupportTicket.objects.get(user=self.customer)
        self.assertRedirects(
            response,
            reverse(
                "marketplace:support_ticket_detail",
                args=[ticket.ticket_number],
            ),
        )
        return ticket

    def test_non_staff_cannot_access_registered_user_administration(self):
        self.client.force_login(self.customer)
        self.assertEqual(
            self.client.get(reverse("marketplace:registered_users_admin")).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "marketplace:registered_user_action_admin",
                    args=[self.other.pk],
                ),
                {"action": "suspend", "reason": "Attempted bypass"},
            ).status_code,
            403,
        )

    def test_admin_can_search_users_without_exposing_credentials(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("marketplace:registered_users_admin"),
            {"q": "customer@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Support Customer")
        self.assertNotContains(response, self.customer.password)

    def test_registered_user_detail_renders_system_activity_without_actor(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse(
                "marketplace:registered_user_detail_admin",
                args=[self.customer.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Account Registered")
        self.assertContains(response, "System")

    def test_account_suspension_requires_reason_and_restore_is_validated(self):
        self.client.force_login(self.admin)
        action_url = reverse(
            "marketplace:registered_user_action_admin",
            args=[self.customer.pk],
        )
        self.client.post(action_url, {"action": "suspend", "reason": ""})
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)

        self.client.post(
            action_url,
            {"action": "suspend", "reason": "Repeated marketplace policy violations."},
        )
        self.customer.refresh_from_db()
        state = self.customer.marketplace_account_state
        self.assertFalse(self.customer.is_active)
        self.assertEqual(state.status, UserAccountState.SUSPENDED)

        self.client.post(action_url, {"action": "restore"})
        self.customer.refresh_from_db()
        state.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertEqual(state.status, UserAccountState.ACTIVE)

    def test_customer_can_only_open_own_support_ticket(self):
        ticket = self.create_ticket()
        self.client.force_login(self.other)
        response = self.client.get(
            reverse(
                "marketplace:support_ticket_detail",
                args=[ticket.ticket_number],
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_ticket_creation_uses_reference_number_and_notifies_staff(self):
        ticket = self.create_ticket()
        self.assertRegex(ticket.ticket_number, r"^SUP-\d{4}-\d{5}$")
        self.assertEqual(ticket.priority, SupportTicket.NORMAL)
        self.assertEqual(ticket.messages.count(), 1)
        self.assertTrue(
            MarketplaceNotification.objects.filter(
                recipient=self.admin,
                support_ticket=ticket,
                notification_type=MarketplaceNotification.SUPPORT,
            ).exists()
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "marketplace:support_ticket_detail",
                    args=[ticket.ticket_number],
                )
            ).status_code,
            200,
        )
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(
                reverse(
                    "marketplace:admin_support_ticket_detail",
                    args=[ticket.ticket_number],
                )
            ).status_code,
            200,
        )

    def test_admin_reply_and_status_change_notify_customer(self):
        ticket = self.create_ticket()
        self.client.force_login(self.admin)
        detail_url = reverse(
            "marketplace:admin_support_ticket_detail",
            args=[ticket.ticket_number],
        )
        self.client.post(
            detail_url,
            {"form_action": "reply", "body": "Please try signing in again."},
        )
        self.assertTrue(
            SupportMessage.objects.filter(ticket=ticket, sender=self.admin).exists()
        )
        self.assertTrue(
            MarketplaceNotification.objects.filter(
                recipient=self.customer,
                support_ticket=ticket,
                title__startswith="Support replied",
            ).exists()
        )
        self.client.post(
            detail_url,
            {
                "form_action": "update",
                "status": SupportTicket.IN_PROGRESS,
                "priority": SupportTicket.HIGH,
            },
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, SupportTicket.IN_PROGRESS)
        self.assertEqual(ticket.priority, SupportTicket.HIGH)
        self.assertTrue(
            MarketplaceNotification.objects.filter(
                recipient=self.customer,
                support_ticket=ticket,
                title__contains="is now In Progress",
            ).exists()
        )

    def test_dangerous_attachment_type_is_rejected(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("marketplace:support_ticket_create"),
            {
                "subject": "Attachment validation",
                "category": SupportTicket.TECHNICAL,
                "description": "This file must be rejected.",
                "attachment": SimpleUploadedFile(
                    "payload.exe",
                    b"MZ dangerous",
                    content_type="application/x-msdownload",
                ),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload a valid JPG, PNG, or PDF file.")
        self.assertFalse(SupportTicket.objects.filter(user=self.customer).exists())


class MarketplaceWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", password="testpass123", is_staff=True)
        self.buyer = User.objects.create_user("buyer", password="testpass123")
        self.other_buyer = User.objects.create_user("other", password="testpass123")
        self.farm_operator = User.objects.create_user("farmowner", password="testpass123")
        farm_group, _ = Group.objects.get_or_create(name=FARM_OPERATOR_GROUP_NAME)
        self.farm_operator.groups.add(farm_group)
        self.admin_seller_profile = SellerProfile.objects.create(
            user=self.admin,
            farm_name="GoHMoTech Smart Farm",
            barangay="San Roque",
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09170000000",
            farm_description="Original smart farm seller.",
            address_details="Private client farm address",
            status=SellerProfile.APPROVED,
            approved_at=timezone.now(),
        )
        self.goat = Goat.objects.create(
            goat_id="GT-MKT-001",
            name="Market Goat",
            breed="native",
            gender="female",
            health_status="healthy",
            status="active",
            is_active=True,
            owner=self.admin,
        )
        self.listing = MarketplaceListing.objects.create(
            goat=self.goat,
            seller=self.admin,
            price=Decimal("12500.00"),
            sales_description="Healthy farm goat.",
            status=MarketplaceListing.AVAILABLE,
            published_at=timezone.now(),
        )
        self.conversation = Conversation.objects.create(listing=self.listing, buyer=self.buyer)

    def _create_available_listing(self, goat_id="GT-MKT-002"):
        goat = Goat.objects.create(
            goat_id=goat_id,
            name="Second Market Goat",
            breed="boer",
            gender="male",
            health_status="healthy",
            status="active",
            is_active=True,
            owner=self.admin,
        )
        return MarketplaceListing.objects.create(
            goat=goat,
            seller=self.admin,
            price=Decimal("14500.00"),
            sales_description="Another healthy farm goat.",
            status=MarketplaceListing.AVAILABLE,
            published_at=timezone.now() + timedelta(minutes=1),
        )

    def test_admin_can_choose_homepage_feature(self):
        newer_listing = self._create_available_listing()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("marketplace:listing_featured", args=[self.listing.pk]),
            {"action": "feature"},
        )

        self.assertRedirects(response, reverse("marketplace:admin_dashboard"))
        self.listing.refresh_from_db()
        self.assertTrue(self.listing.is_featured)
        landing = self.client.get(reverse("marketplace:landing"))
        self.assertEqual(landing.context["featured_listings"][0].pk, self.listing.pk)
        self.assertNotEqual(landing.context["featured_listings"][0].pk, newer_listing.pk)

    def test_choosing_feature_replaces_previous_selection(self):
        second_listing = self._create_available_listing()
        self.listing.is_featured = True
        self.listing.save(update_fields=["is_featured"])
        self.client.force_login(self.admin)

        self.client.post(
            reverse("marketplace:listing_featured", args=[second_listing.pk]),
            {"action": "feature"},
        )

        self.listing.refresh_from_db()
        second_listing.refresh_from_db()
        self.assertFalse(self.listing.is_featured)
        self.assertTrue(second_listing.is_featured)
        self.assertEqual(MarketplaceListing.objects.filter(is_featured=True).count(), 1)

    def test_non_staff_cannot_change_homepage_feature(self):
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("marketplace:listing_featured", args=[self.listing.pk]),
            {"action": "feature"},
        )

        self.assertEqual(response.status_code, 403)
        self.listing.refresh_from_db()
        self.assertFalse(self.listing.is_featured)

    def test_unavailable_listing_cannot_be_featured(self):
        self.listing.status = MarketplaceListing.DRAFT
        self.listing.save(update_fields=["status"])
        self.client.force_login(self.admin)

        self.client.post(
            reverse("marketplace:listing_featured", args=[self.listing.pk]),
            {"action": "feature"},
        )

        self.listing.refresh_from_db()
        self.assertFalse(self.listing.is_featured)

    def test_inquiry_does_not_reserve_goat(self):
        self.client.force_login(self.other_buyer)
        response = self.client.post(reverse("marketplace:start_inquiry", args=[self.listing.pk]))
        self.assertEqual(response.status_code, 302)
        self.listing.refresh_from_db()
        self.goat.refresh_from_db()
        self.assertEqual(self.listing.status, MarketplaceListing.AVAILABLE)
        self.assertEqual(self.goat.status, "active")

    def test_only_one_pending_request_can_be_accepted(self):
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )
        self.listing.refresh_from_db()
        self.goat.refresh_from_db()
        self.assertEqual(reservation.agreed_price, Decimal("12500.00"))
        self.assertEqual(reservation.status, Reservation.PENDING)
        self.assertEqual(self.listing.status, MarketplaceListing.AVAILABLE)
        self.assertEqual(self.goat.status, "active")
        self.assertTrue(self.goat.is_active)

        other_conversation = Conversation.objects.create(listing=self.listing, buyer=self.other_buyer)
        competing = request_reservation(
            self.listing.pk, self.other_buyer, other_conversation
        )
        accept_reservation(reservation.pk, self.admin)
        reservation.refresh_from_db()
        competing.refresh_from_db()
        self.listing.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.ACCEPTED)
        self.assertEqual(competing.status, Reservation.REJECTED)
        self.assertEqual(self.listing.status, MarketplaceListing.RESERVED)

        with self.assertRaises(ValidationError):
            request_reservation(self.listing.pk, self.other_buyer, other_conversation)

    def test_cancel_returns_listing_to_available(self):
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )
        accept_reservation(reservation.pk, self.admin)
        cancel_reservation(reservation.pk, self.admin, "Buyer cancelled")
        reservation.refresh_from_db()
        self.listing.refresh_from_db()
        self.goat.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.CANCELLED)
        self.assertEqual(self.listing.status, MarketplaceListing.AVAILABLE)
        self.assertEqual(self.goat.status, "active")

    def test_farm_owner_without_seller_profile_can_view_accepted_reservations(self):
        farm_owner = User.objects.create_user("reservation-farm-owner")
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        farm_owner.groups.add(owner_group)
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )
        accept_reservation(reservation.pk, self.admin)

        self.client.force_login(farm_owner)
        response = self.client.get(reverse("marketplace:seller_reservations"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GT-MKT-001")
        self.assertEqual(response.context["default_pickup_location"], "")

    def test_completion_requires_confirmed_pickup_and_marks_existing_goat_sold(self):
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )
        accept_reservation(reservation.pk, self.admin)
        with self.assertRaises(ValidationError):
            complete_sale(reservation.pk, self.admin)

        request_pickup(
            reservation.pk,
            self.buyer,
            timezone.now() + timedelta(days=1),
            "Morning pickup",
        )
        confirm_pickup(reservation.pk, self.admin)
        complete_sale(reservation.pk, self.admin)

        reservation.refresh_from_db()
        self.listing.refresh_from_db()
        self.goat.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.COMPLETED)
        self.assertEqual(self.listing.status, MarketplaceListing.SOLD)
        self.assertEqual(self.goat.status, "sold")
        self.assertFalse(self.goat.is_active)

    def test_private_conversation_is_not_visible_to_another_buyer(self):
        self.client.force_login(self.other_buyer)
        response = self.client.get(reverse("marketplace:conversation", args=[self.conversation.pk]))
        self.assertRedirects(response, reverse("marketplace:my_inquiries"))

    def test_non_staff_cannot_open_marketplace_admin(self):
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("marketplace:admin_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_admin_dashboard_paginates_without_per_listing_queries(self):
        for number in range(2, 29):
            self._create_available_listing(f'GT-MKT-{number:03d}')
        self.client.force_login(self.admin)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('marketplace:admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['listings']), 25)
        self.assertTrue(response.context['listing_page'].has_next())
        # A prefetched image query and consolidated counts keep this independent
        # of how many listing rows appear on the page.
        self.assertLessEqual(len(queries), 20)

    def test_public_and_staff_pages_render(self):
        self.assertEqual(self.client.get(reverse("marketplace:landing")).status_code, 200)
        self.assertEqual(self.client.get(reverse("marketplace:list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("marketplace:buyer_login")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("marketplace:detail", args=[self.listing.pk])).status_code,
            200,
        )
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("marketplace:admin_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("marketplace:listing_add")).status_code, 200)

    def test_registered_buyer_is_separated_from_farm_dashboard(self):
        response = self.client.post(
            reverse("marketplace:register"),
            {
                "first_name": "New",
                "last_name": "Buyer",
                "email": "buyer@example.com",
                "password1": "A-strong-test-password-123",
                "password2": "A-strong-test-password-123",
            },
        )
        self.assertRedirects(response, reverse("marketplace:list"))
        registered = User.objects.get(email="buyer@example.com")
        self.assertTrue(registered.username)
        self.assertTrue(registered.groups.filter(name=BUYER_GROUP_NAME).exists())
        self.assertFalse(has_farm_access(registered))
        response = self.client.get("/iot/")
        self.assertRedirects(response, reverse("marketplace:list"))
        response = self.client.get("/")
        self.assertRedirects(response, "/marketplace/")

    def test_existing_user_can_sign_in_with_email(self):
        self.buyer.email = "existing@example.com"
        self.buyer.save(update_fields=["email"])

        response = self.client.post(
            reverse("marketplace:buyer_login"),
            {
                "login": "existing@example.com",
                "password": "testpass123",
                "next": reverse("marketplace:list"),
            },
        )

        self.assertRedirects(response, reverse("marketplace:list"))

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="test-client.apps.googleusercontent.com",
        GOOGLE_OAUTH_CLIENT_SECRET="test-secret",
    )
    def test_google_button_posts_to_real_provider_endpoint_when_configured(self):
        response = self.client.get(reverse("marketplace:register"))

        self.assertContains(response, "Continue with Google")
        self.assertContains(response, 'action="/accounts/google/login/"')
        self.assertContains(response, 'method="post"')

    def test_google_signup_receives_buyer_role_without_farm_access(self):
        google_user = User.objects.create_user(
            "google-user",
            email="google@example.com",
        )

        user_signed_up.send(
            sender=User,
            request=None,
            user=google_user,
        )

        self.assertTrue(
            google_user.groups.filter(name=BUYER_GROUP_NAME).exists()
        )
        self.assertFalse(has_farm_access(google_user))

    def test_google_auth_security_configuration(self):
        google = settings.SOCIALACCOUNT_PROVIDERS["google"]

        self.assertFalse(settings.SOCIALACCOUNT_LOGIN_ON_GET)
        self.assertFalse(settings.SOCIALACCOUNT_STORE_TOKENS)
        self.assertTrue(settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT)
        self.assertTrue(google["OAUTH_PKCE_ENABLED"])
        self.assertTrue(google["EMAIL_AUTHENTICATION"])

    def test_email_identity_is_unique_at_database_level(self):
        first = User.objects.create_user("email-owner")
        second = User.objects.create_user("email-conflict")
        EmailAddress.objects.create(
            user=first,
            email="unique@example.com",
            primary=True,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            EmailAddress.objects.create(
                user=second,
                email="unique@example.com",
                primary=True,
            )

    def test_google_user_with_missing_name_must_complete_short_profile(self):
        SocialAccount.objects.create(
            user=self.other_buyer,
            provider="google",
            uid="google-subject-123",
            extra_data={"email": "google@example.com", "email_verified": True},
        )
        self.client.force_login(self.other_buyer)

        response = self.client.get(reverse("marketplace:list"))
        self.assertRedirects(response, reverse("marketplace:complete_profile"))

        response = self.client.post(
            reverse("marketplace:complete_profile"),
            {"first_name": "Google", "last_name": "Buyer"},
        )
        self.assertRedirects(response, reverse("marketplace:list"))
        self.other_buyer.refresh_from_db()
        self.assertEqual(self.other_buyer.get_full_name(), "Google Buyer")
        self.assertEqual(
            self.client.get(reverse("marketplace:list")).status_code,
            200,
        )

    def test_marketplace_account_is_blocked_even_without_legacy_buyer_group(self):
        self.assertFalse(self.other_buyer.groups.exists())
        self.client.force_login(self.other_buyer)

        for path in ("/iot/", "/overview/", "/analytics/", "/feeding/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertRedirects(response, reverse("marketplace:list"))

    def test_marketplace_account_gets_json_403_from_farm_api(self):
        self.client.force_login(self.other_buyer)
        response = self.client.get("/iot/api/devices/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {"detail": "This account does not have access to farm operations."},
        )

    def test_explicit_farm_operator_keeps_farm_access(self):
        self.client.force_login(self.farm_operator)

        self.assertRedirects(
            self.client.get("/"),
            "/iot/owner/",
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.get("/overview/").status_code, 200)

    def test_catalog_search_filter_and_sort(self):
        response = self.client.get(
            reverse("marketplace:list"),
            {"q": "GT-MKT", "breed": "native", "sort": "price_high"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GT-MKT-001")
        self.assertEqual(response.context["result_count"], 1)

    def test_published_farm_owner_listing_is_visible_in_public_catalog(self):
        farm_owner = User.objects.create_user("catalog-farm-owner")
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        farm_owner.groups.add(owner_group)
        goat = Goat.objects.create(
            goat_id="GT-OWNER-001",
            name="Owner Market Goat",
            breed="boer",
            gender="male",
            health_status="healthy",
            status="active",
            is_active=True,
            owner=farm_owner,
        )
        listing = MarketplaceListing.objects.create(
            goat=goat,
            seller=farm_owner,
            price=Decimal("15000.00"),
            sales_description="Published by an authorized farm owner.",
            status=MarketplaceListing.AVAILABLE,
            published_at=timezone.now(),
        )

        catalog = self.client.get(reverse("marketplace:list"))
        detail = self.client.get(reverse("marketplace:detail", args=[listing.pk]))

        self.assertContains(catalog, "GT-OWNER-001")
        self.assertEqual(detail.status_code, 200)

    def test_detail_renders_slider_for_multiple_goat_images(self):
        GoatImage.objects.create(
            goat=self.goat,
            image="goat_images/report-front.jpg",
            image_type="profile",
            description="Front view",
        )
        GoatImage.objects.create(
            goat=self.goat,
            image="goat_images/report-side.jpg",
            image_type="full_body",
            description="Side view",
        )
        response = self.client.get(reverse("marketplace:detail", args=[self.listing.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-goat-gallery")
        self.assertContains(response, 'class="gallery-slide', count=2)
        self.assertContains(response, 'class="gallery-thumbnail', count=2)
        self.assertContains(response, "data-gallery-next")
        self.assertContains(response, "data-gallery-lightbox")

    def test_storefront_includes_mobile_navigation_and_catalog_filters(self):
        landing = self.client.get(reverse("marketplace:landing"))
        self.assertContains(landing, 'name="viewport"')
        self.assertContains(landing, "mobile-nav-actions")
        self.assertContains(landing, "data-nav-toggle")
        self.assertContains(landing, "images/gohmotech-logo.png", count=4)

        catalog = self.client.get(reverse("marketplace:list"))
        self.assertContains(catalog, "data-filter-toggle")
        self.assertContains(catalog, "marketplaceFilters")

    def test_farm_accounts_get_role_aware_dashboard_link_in_marketplace(self):
        owner = User.objects.create_user("marketplace-farm-owner")
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        owner.groups.add(owner_group)

        for user, expected_url in (
            (self.admin, reverse("iot:dashboard")),
            (owner, reverse("iot:owner_dashboard")),
            (self.farm_operator, reverse("iot:owner_dashboard")),
        ):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(reverse("marketplace:list"))
                self.assertContains(response, "Back to Dashboard", count=2)
                self.assertContains(response, f'href="{expected_url}"', count=2)

    def test_marketplace_only_buyer_does_not_get_farm_dashboard_link(self):
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("marketplace:list"))
        self.assertNotContains(response, "Back to Dashboard")

    def test_main_login_page_renders_enhanced_authentication_layout(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secure farm operations")
        self.assertContains(response, "data-password-toggle")
        self.assertContains(response, "Browse the public marketplace")
        self.assertContains(response, 'name="viewport"')

    def test_main_login_preserves_username_and_next_after_error(self):
        response = self.client.post(
            reverse("login") + "?next=/analytics/",
            {"login": "wrong-user", "password": "wrong-password", "next": "/analytics/"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="wrong-user"')
        self.assertContains(response, 'name="next" value="/analytics/"')
        self.assertContains(response, "We couldn't sign you in")

    def seller_application_data(self, **overrides):
        data = {
            "first_name": "Community",
            "last_name": "Owner",
            "farm_name": "Green Hills Goat Farm",
            "barangay": "San Roque",
            "municipality": "San Jose",
            "province": "Nueva Ecija",
            "contact_number": "+63 912 345 6789",
            "farm_description": "Small community goat farm.",
            "address_details": "Private pickup landmark",
        }
        data.update(overrides)
        return data

    def test_buyer_can_apply_as_pending_seller_without_farm_access(self):
        self.client.force_login(self.buyer)
        response = self.client.post(
            reverse("marketplace:seller_application"),
            self.seller_application_data(),
        )

        self.assertRedirects(response, reverse("marketplace:seller_application"))
        profile = SellerProfile.objects.get(user=self.buyer)
        self.assertEqual(profile.status, SellerProfile.PENDING)
        self.assertFalse(is_approved_seller(self.buyer))
        self.assertFalse(has_farm_access(self.buyer))
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.get_full_name(), "Community Owner")

    def test_seller_application_rejects_document_with_spoofed_pdf_type(self):
        self.client.force_login(self.buyer)
        fake_pdf = SimpleUploadedFile(
            'identity.pdf',
            b'<script>alert(1)</script>',
            content_type='application/pdf',
        )

        response = self.client.post(
            reverse('marketplace:seller_application'),
            self.seller_application_data(supporting_document=fake_pdf),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'does not match its file type')
        self.assertFalse(SellerProfile.objects.filter(user=self.buyer).exists())

    def test_admin_cannot_open_or_post_seller_application(self):
        original_name = self.admin_seller_profile.farm_name
        self.client.force_login(self.admin)

        get_response = self.client.get(reverse("marketplace:seller_application"))
        self.assertRedirects(get_response, reverse("marketplace:admin_dashboard"))

        post_response = self.client.post(
            reverse("marketplace:seller_application"),
            self.seller_application_data(farm_name="Invalid Admin Application"),
        )
        self.assertRedirects(post_response, reverse("marketplace:admin_dashboard"))
        self.admin_seller_profile.refresh_from_db()
        self.assertEqual(self.admin_seller_profile.farm_name, original_name)

    def test_farm_operator_cannot_submit_seller_application(self):
        self.client.force_login(self.farm_operator)
        response = self.client.post(
            reverse("marketplace:seller_application"),
            self.seller_application_data(farm_name="Invalid Operator Application"),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SellerProfile.objects.filter(user=self.farm_operator).exists())

    def test_staff_profile_is_not_a_reviewable_community_application(self):
        staff_applicant = User.objects.create_user(
            "invalidstaff", password="testpass123", is_staff=True
        )
        profile = SellerProfile.objects.create(
            user=staff_applicant,
            farm_name="Invalid Staff Application",
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="Created before staff application access was blocked.",
        )
        self.client.force_login(self.admin)
        action_url = reverse("marketplace:seller_application_action", args=[profile.pk])

        approve_response = self.client.post(action_url, {"action": "approve"}, follow=True)
        profile.refresh_from_db()
        self.assertEqual(profile.status, SellerProfile.PENDING)
        self.assertContains(approve_response, "not community seller applications")
        management = self.client.get(reverse("marketplace:seller_applications_admin"))
        self.assertNotContains(management, "Invalid Staff Application")

        decline_response = self.client.post(
            action_url,
            {"action": "reject", "reason": "Staff accounts are not eligible."},
            follow=True,
        )
        profile.refresh_from_db()
        self.assertEqual(profile.status, SellerProfile.PENDING)
        self.assertIsNone(profile.reviewed_by)
        self.assertContains(decline_response, "not community seller applications")

    def test_admin_cannot_review_own_farm_profile_as_an_application(self):
        self.admin_seller_profile.status = SellerProfile.PENDING
        self.admin_seller_profile.save(update_fields=["status"])
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse(
                "marketplace:seller_application_action",
                args=[self.admin_seller_profile.pk],
            ),
            {"action": "reject", "reason": "Invalid legacy staff application."},
            follow=True,
        )

        self.admin_seller_profile.refresh_from_db()
        self.assertEqual(self.admin_seller_profile.status, SellerProfile.PENDING)
        self.assertContains(response, "not community seller applications")

    def test_admin_farm_listing_remains_public_independent_of_application_status(self):
        self.admin_seller_profile.status = SellerProfile.REJECTED
        self.admin_seller_profile.save(update_fields=["status"])

        landing = self.client.get(reverse("marketplace:landing"))
        catalog = self.client.get(reverse("marketplace:list"))
        detail = self.client.get(reverse("marketplace:detail", args=[self.listing.pk]))

        self.assertContains(landing, self.goat.goat_id)
        self.assertContains(catalog, self.goat.goat_id)
        self.assertContains(detail, "GoHMoTech Smart Farm")

        self.client.force_login(self.other_buyer)
        inquiry = self.client.post(
            reverse("marketplace:start_inquiry", args=[self.listing.pk])
        )
        self.assertEqual(inquiry.status_code, 302)
        self.assertTrue(
            Conversation.objects.filter(listing=self.listing, buyer=self.other_buyer).exists()
        )

    def test_pending_seller_cannot_open_seller_dashboard(self):
        SellerProfile.objects.create(
            user=self.buyer,
            farm_name="Pending Farm",
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="Pending review.",
        )
        self.client.force_login(self.buyer)

        response = self.client.get(reverse("marketplace:seller_dashboard"))

        self.assertRedirects(response, reverse("marketplace:seller_application"))

    def test_admin_can_approve_seller_without_granting_farm_access(self):
        profile = SellerProfile.objects.create(
            user=self.buyer,
            farm_name="Approved Farm",
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="For approval.",
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("marketplace:seller_application_action", args=[profile.pk]),
            {"action": "approve"},
        )
        self.assertRedirects(response, reverse("marketplace:seller_applications_admin"))

        profile.refresh_from_db()
        self.assertEqual(profile.status, SellerProfile.APPROVED)
        self.assertEqual(profile.reviewed_by, self.admin)
        self.assertIsNotNone(profile.approved_at)
        self.assertTrue(is_approved_seller(self.buyer))
        self.assertFalse(has_farm_access(self.buyer))

        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse("marketplace:seller_dashboard")).status_code, 200)
        self.assertRedirects(self.client.get("/iot/"), reverse("marketplace:list"))

    def test_buyer_cannot_approve_seller(self):
        profile = SellerProfile.objects.create(
            user=self.other_buyer,
            farm_name="Other Farm",
            municipality="Cabanatuan",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="For approval.",
        )
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("marketplace:seller_application_action", args=[profile.pk]),
            {"action": "approve"},
        )

        self.assertEqual(response.status_code, 403)
        profile.refresh_from_db()
        self.assertEqual(profile.status, SellerProfile.PENDING)

    def test_rejection_and_suspension_require_a_reason(self):
        profile = SellerProfile.objects.create(
            user=self.buyer,
            farm_name="Review Farm",
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="For review.",
        )
        self.client.force_login(self.admin)
        action_url = reverse("marketplace:seller_application_action", args=[profile.pk])

        self.client.post(action_url, {"action": "reject", "reason": ""})
        profile.refresh_from_db()
        self.assertEqual(profile.status, SellerProfile.PENDING)

        self.client.post(action_url, {"action": "approve"})
        self.client.post(action_url, {"action": "suspend", "reason": ""})
        profile.refresh_from_db()
        self.assertEqual(profile.status, SellerProfile.APPROVED)

        self.client.post(action_url, {"action": "suspend", "reason": "Policy violation"})
        profile.refresh_from_db()
        self.assertEqual(profile.status, SellerProfile.SUSPENDED)
        self.assertEqual(profile.review_reason, "Policy violation")

    def test_nonapproved_seller_profile_is_not_public(self):
        profile = SellerProfile.objects.create(
            user=self.buyer,
            farm_name="Private Pending Farm",
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="Pending.",
        )

        response = self.client.get(reverse("marketplace:seller_profile", args=[profile.pk]))

        self.assertRedirects(response, reverse("marketplace:list"))

    def test_public_seller_profile_hides_private_contact_and_address(self):
        profile = SellerProfile.objects.create(
            user=self.buyer,
            farm_name="Public Farm",
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="Public description.",
            address_details="Secret pickup landmark",
            status=SellerProfile.APPROVED,
            approved_at=timezone.now(),
        )

        response = self.client.get(reverse("marketplace:seller_profile", args=[profile.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Approved Seller")
        self.assertContains(response, "Public description.")
        self.assertNotContains(response, "09123456789")
        self.assertNotContains(response, "Secret pickup landmark")

    def test_approved_profile_changes_return_to_pending_review(self):
        profile = SellerProfile.objects.create(
            user=self.buyer,
            farm_name="Original Farm",
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="Original description.",
            status=SellerProfile.APPROVED,
            approved_at=timezone.now(),
            reviewed_by=self.admin,
            reviewed_at=timezone.now(),
        )
        self.client.force_login(self.buyer)

        self.client.post(
            reverse("marketplace:seller_application"),
            self.seller_application_data(farm_name="Updated Farm"),
        )

        profile.refresh_from_db()
        self.assertEqual(profile.farm_name, "Updated Farm")
        self.assertEqual(profile.status, SellerProfile.PENDING)
        self.assertIsNone(profile.reviewed_by)
        self.assertFalse(is_approved_seller(self.buyer))

    def approve_seller(self, user, farm_name="Community Farm"):
        return SellerProfile.objects.create(
            user=user,
            farm_name=farm_name,
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="Approved community seller.",
            status=SellerProfile.APPROVED,
            approved_at=timezone.now(),
        )

    def goat_photo(self, name="goat.png"):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        return SimpleUploadedFile(name, png, content_type="image/png")

    def community_goat_data(self, **overrides):
        data = {
            "name": "Seller Goat",
            "tag_number": "LOCAL-01",
            "breed": "native",
            "gender": "female",
            "date_of_birth": "2025-01-01",
            "weight_kg": "28.5",
            "color_markings": "Brown and white",
            "health_status": "healthy",
            "health_notes": "Observed healthy",
            "vaccination_status": "unknown",
            "vaccine_name": "",
            "vaccination_date": "",
            "next_due_date": "",
            "notes": "Manual community record",
            "photos": self.goat_photo(),
        }
        data.update(overrides)
        return data

    def test_approved_seller_creates_owned_community_goat_with_photo(self):
        self.approve_seller(self.buyer)
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("marketplace:seller_goat_add"),
            self.community_goat_data(),
        )

        self.assertRedirects(response, reverse("marketplace:seller_goats"))
        goat = Goat.all_objects.get(owner=self.buyer)
        self.assertEqual(goat.record_source, Goat.COMMUNITY)
        self.assertEqual(goat.status, "active")
        self.assertEqual(goat.images.count(), 1)
        self.assertFalse(Goat.objects.filter(pk=goat.pk).exists())

    def test_pending_seller_cannot_create_community_goat(self):
        SellerProfile.objects.create(
            user=self.buyer,
            farm_name="Pending Farm",
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="Pending.",
        )
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("marketplace:seller_goat_add"),
            self.community_goat_data(),
        )

        self.assertRedirects(response, reverse("marketplace:seller_application"))
        self.assertFalse(Goat.all_objects.filter(owner=self.buyer).exists())

    def test_seller_b_cannot_modify_seller_a_goat(self):
        self.approve_seller(self.buyer, "Seller A")
        self.approve_seller(self.other_buyer, "Seller B")
        goat = Goat.all_objects.create(
            goat_id="CM-A-PRIVATE",
            name="Seller A Goat",
            breed="native",
            gender="female",
            owner=self.buyer,
            record_source=Goat.COMMUNITY,
        )
        self.client.force_login(self.other_buyer)

        response = self.client.post(
            reverse("marketplace:seller_goat_edit", args=[goat.pk]),
            self.community_goat_data(name="stolen.png"),
        )

        self.assertEqual(response.status_code, 404)
        goat.refresh_from_db()
        self.assertEqual(goat.name, "Seller A Goat")

    def test_seller_listing_form_rejects_another_sellers_goat(self):
        self.approve_seller(self.buyer, "Seller A")
        self.approve_seller(self.other_buyer, "Seller B")
        goat = Goat.all_objects.create(
            goat_id="CM-A-LIST",
            breed="native",
            gender="male",
            owner=self.buyer,
            record_source=Goat.COMMUNITY,
        )
        GoatImage.objects.create(goat=goat, image="goat_images/seller-a.jpg")
        self.client.force_login(self.other_buyer)

        response = self.client.post(
            reverse("marketplace:seller_listing_add"),
            {"goat": goat.pk, "price": "15000.00", "sales_description": "Not mine"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(MarketplaceListing.objects.filter(goat=goat).exists())

    def test_seller_can_publish_only_owned_goat_with_photo(self):
        self.approve_seller(self.buyer)
        goat = Goat.all_objects.create(
            goat_id="CM-OWN-PUBLISH",
            breed="native",
            gender="female",
            owner=self.buyer,
            record_source=Goat.COMMUNITY,
        )
        GoatImage.objects.create(goat=goat, image="goat_images/owned.jpg")
        self.client.force_login(self.buyer)
        create_response = self.client.post(
            reverse("marketplace:seller_listing_add"),
            {"goat": goat.pk, "price": "18000.00", "sales_description": "Owned goat"},
        )
        self.assertRedirects(create_response, reverse("marketplace:seller_listings"))
        listing = MarketplaceListing.objects.get(goat=goat)
        self.assertEqual(listing.status, MarketplaceListing.DRAFT)

        publish_response = self.client.post(
            reverse("marketplace:seller_listing_publication", args=[listing.pk]),
            {"action": "publish"},
        )
        self.assertRedirects(publish_response, reverse("marketplace:seller_listings"))
        listing.refresh_from_db()
        self.assertEqual(listing.status, MarketplaceListing.AVAILABLE)
        self.assertEqual(listing.seller, self.buyer)

    def test_seller_b_cannot_edit_or_publish_seller_a_listing(self):
        self.approve_seller(self.buyer, "Seller A")
        self.approve_seller(self.other_buyer, "Seller B")
        goat = Goat.all_objects.create(
            goat_id="CM-A-SECURE",
            breed="native",
            gender="female",
            owner=self.buyer,
            record_source=Goat.COMMUNITY,
        )
        GoatImage.objects.create(goat=goat, image="goat_images/a-secure.jpg")
        listing = MarketplaceListing.objects.create(
            goat=goat,
            seller=self.buyer,
            price="12000.00",
            sales_description="Seller A listing",
        )
        self.client.force_login(self.other_buyer)

        self.assertEqual(
            self.client.get(reverse("marketplace:seller_listing_edit", args=[listing.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("marketplace:seller_listing_publication", args=[listing.pk]),
                {"action": "publish"},
            ).status_code,
            404,
        )

    def test_suspension_unpublishes_listing_and_blocks_seller_management(self):
        profile = self.approve_seller(self.buyer)
        goat = Goat.all_objects.create(
            goat_id="CM-SUSPEND",
            breed="native",
            gender="female",
            owner=self.buyer,
            record_source=Goat.COMMUNITY,
        )
        listing = MarketplaceListing.objects.create(
            goat=goat,
            seller=self.buyer,
            price="12500.00",
            sales_description="Will be suspended",
            status=MarketplaceListing.AVAILABLE,
            published_at=timezone.now(),
        )
        self.client.force_login(self.admin)
        self.client.post(
            reverse("marketplace:seller_application_action", args=[profile.pk]),
            {"action": "suspend", "reason": "Policy violation"},
        )
        listing.refresh_from_db()
        self.assertEqual(listing.status, MarketplaceListing.DRAFT)

        self.client.force_login(self.buyer)
        self.assertRedirects(
            self.client.get(reverse("marketplace:seller_goats")),
            reverse("marketplace:seller_application"),
        )

    def test_seller_cannot_inquire_about_or_reserve_own_listing(self):
        self.approve_seller(self.buyer)
        goat = Goat.all_objects.create(
            goat_id="CM-SELF",
            breed="native",
            gender="male",
            owner=self.buyer,
            record_source=Goat.COMMUNITY,
        )
        listing = MarketplaceListing.objects.create(
            goat=goat,
            seller=self.buyer,
            price="10000.00",
            sales_description="Own listing",
            status=MarketplaceListing.AVAILABLE,
        )
        self.client.force_login(self.buyer)
        response = self.client.post(reverse("marketplace:start_inquiry", args=[listing.pk]))
        self.assertRedirects(response, reverse("marketplace:detail", args=[listing.pk]))
        self.assertFalse(Conversation.objects.filter(listing=listing, buyer=self.buyer).exists())

        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        with self.assertRaises(ValidationError):
            request_reservation(listing.pk, self.buyer, conversation)

    def test_community_goat_requires_owner_at_database_level(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Goat.all_objects.create(
                goat_id="CM-NO-OWNER",
                breed="native",
                gender="female",
                record_source=Goat.COMMUNITY,
            )

    def test_catalog_filters_by_public_location_and_approved_seller(self):
        seller_profile = self.approve_seller(self.buyer, "North Valley Goats")
        seller_profile.barangay = "Maligaya"
        seller_profile.municipality = "Cabanatuan"
        seller_profile.province = "Nueva Ecija"
        seller_profile.save(update_fields=["barangay", "municipality", "province"])
        goat = Goat.all_objects.create(
            goat_id="CM-LOCATION",
            breed="boer",
            gender="male",
            owner=self.buyer,
            record_source=Goat.COMMUNITY,
        )
        MarketplaceListing.objects.create(
            goat=goat,
            seller=self.buyer,
            price="20000.00",
            sales_description="Community Boer goat",
            status=MarketplaceListing.AVAILABLE,
            published_at=timezone.now(),
        )

        response = self.client.get(
            reverse("marketplace:list"),
            {
                "province": "Nueva Ecija",
                "municipality": "Cabanatuan",
                "barangay": "Maligaya",
                "seller": seller_profile.pk,
            },
        )

        self.assertEqual(response.context["result_count"], 1)
        self.assertContains(response, "CM-LOCATION")
        self.assertContains(response, "North Valley Goats")
        self.assertContains(response, "Maligaya, Cabanatuan, Nueva Ecija")

    def test_catalog_keyword_searches_seller_and_location(self):
        response = self.client.get(reverse("marketplace:list"), {"q": "Smart Farm"})
        self.assertEqual(response.context["result_count"], 1)
        self.assertContains(response, "GT-MKT-001")

        response = self.client.get(reverse("marketplace:list"), {"q": "San Roque"})
        self.assertEqual(response.context["result_count"], 1)

    def test_catalog_excludes_nonapproved_seller_listings(self):
        pending = SellerProfile.objects.create(
            user=self.buyer,
            farm_name="Pending Seller",
            municipality="San Jose",
            province="Nueva Ecija",
            contact_number="09123456789",
            farm_description="Not approved.",
        )
        goat = Goat.all_objects.create(
            goat_id="CM-PENDING-PUBLIC",
            breed="native",
            gender="female",
            owner=self.buyer,
            record_source=Goat.COMMUNITY,
        )
        MarketplaceListing.objects.create(
            goat=goat,
            seller=self.buyer,
            price="9000.00",
            sales_description="Should be hidden",
            status=MarketplaceListing.AVAILABLE,
        )

        response = self.client.get(reverse("marketplace:list"))

        self.assertNotContains(response, "CM-PENDING-PUBLIC")
        self.assertNotContains(response, pending.farm_name)

    def test_catalog_paginates_twelve_listings_and_preserves_filters(self):
        for index in range(13):
            goat = Goat.objects.create(
                goat_id=f"GT-PAGE-{index:02d}",
                breed="native",
                gender="female",
                owner=self.admin,
            )
            MarketplaceListing.objects.create(
                goat=goat,
                seller=self.admin,
                price=10000 + index,
                sales_description="Pagination goat",
                status=MarketplaceListing.AVAILABLE,
                published_at=timezone.now() + timedelta(minutes=index),
            )

        first_page = self.client.get(
            reverse("marketplace:list"),
            {"province": "Nueva Ecija", "availability": "available"},
        )
        self.assertEqual(first_page.context["result_count"], 14)
        self.assertEqual(len(first_page.context["listings"]), 12)
        self.assertContains(first_page, "province=Nueva+Ecija&amp;availability=available&amp;page=2")

        second_page = self.client.get(
            reverse("marketplace:list"),
            {"province": "Nueva Ecija", "availability": "available", "page": 2},
        )
        self.assertEqual(second_page.context["page_obj"].number, 2)
        self.assertEqual(len(second_page.context["listings"]), 2)

    def test_catalog_card_hides_private_seller_information(self):
        GoatImage.objects.create(
            goat=self.goat,
            image="goat_images/catalog-performance.jpg",
        )
        response = self.client.get(reverse("marketplace:list"))

        self.assertContains(response, "GoHMoTech Smart Farm")
        self.assertNotContains(response, "09170000000")
        self.assertNotContains(response, "Private client farm address")
        self.assertContains(response, 'loading="eager"')

    def test_marketplace_image_optimizer_bounds_phone_photo(self):
        source = BytesIO()
        Image.new("RGB", (2400, 1800), "green").save(source, format="PNG")
        upload = SimpleUploadedFile("phone-photo.png", source.getvalue(), content_type="image/png")

        optimized = optimize_marketplace_image(upload)

        with Image.open(optimized) as result:
            self.assertEqual(result.format, "JPEG")
            self.assertLessEqual(max(result.size), 1600)
        self.assertTrue(optimized.name.endswith(".jpg"))

    def community_listing(self, seller, goat_id="CM-MESSAGE", status=MarketplaceListing.AVAILABLE):
        goat = Goat.all_objects.create(
            goat_id=goat_id,
            name="Message Goat",
            breed="native",
            gender="female",
            owner=seller,
            record_source=Goat.COMMUNITY,
        )
        return MarketplaceListing.objects.create(
            goat=goat,
            seller=seller,
            price="14000.00",
            sales_description="Community seller messaging test.",
            status=status,
            published_at=timezone.now(),
        )

    def test_approved_seller_can_open_inbox_and_reply_to_own_buyer(self):
        self.approve_seller(self.other_buyer, "Seller Inbox Farm")
        listing = self.community_listing(self.other_buyer, "CM-SELLER-REPLY")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        self.client.force_login(self.other_buyer)

        inbox = self.client.get(reverse("marketplace:seller_messages"))
        self.assertEqual(inbox.status_code, 200)
        self.assertContains(inbox, "CM-SELLER-REPLY")

        response = self.client.post(
            reverse("marketplace:conversation", args=[conversation.pk]),
            {"body": "Yes, the goat is available for pickup."},
        )
        self.assertRedirects(
            response, reverse("marketplace:conversation", args=[conversation.pk])
        )
        reply = Message.objects.get(conversation=conversation)
        self.assertEqual(reply.sender, self.other_buyer)

    def test_seller_inbox_counts_unread_and_opening_marks_buyer_message_read(self):
        self.approve_seller(self.other_buyer, "Unread Farm")
        listing = self.community_listing(self.other_buyer, "CM-UNREAD")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        incoming = Message.objects.create(
            conversation=conversation,
            sender=self.buyer,
            body="Is this goat still available?",
        )
        self.client.force_login(self.other_buyer)

        inbox = self.client.get(reverse("marketplace:seller_messages"))
        self.assertContains(inbox, "1 new")
        self.client.get(reverse("marketplace:conversation", args=[conversation.pk]))

        incoming.refresh_from_db()
        self.assertTrue(incoming.is_read)

    def test_seller_cannot_read_another_sellers_conversation(self):
        seller_a = User.objects.create_user("seller-a", password="testpass123")
        seller_b = User.objects.create_user("seller-b", password="testpass123")
        self.approve_seller(seller_a, "Seller A")
        self.approve_seller(seller_b, "Seller B")
        listing = self.community_listing(seller_a, "CM-PRIVATE-CHAT")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        self.client.force_login(seller_b)

        response = self.client.get(
            reverse("marketplace:conversation", args=[conversation.pk])
        )

        self.assertRedirects(response, reverse("marketplace:my_inquiries"))

    def test_staff_moderator_can_read_but_cannot_send_or_mark_unread(self):
        self.approve_seller(self.other_buyer, "Moderated Farm")
        listing = self.community_listing(self.other_buyer, "CM-MODERATED")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        incoming = Message.objects.create(
            conversation=conversation,
            sender=self.buyer,
            body="Buyer message awaiting seller.",
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("marketplace:conversation", args=[conversation.pk]),
            {"body": "Admin must not impersonate a participant."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Read-only moderation view")
        self.assertEqual(conversation.messages.count(), 1)
        incoming.refresh_from_db()
        self.assertFalse(incoming.is_read)

    def test_message_model_rejects_outsider_and_blank_content(self):
        outsider_message = Message(
            conversation=self.conversation,
            sender=self.other_buyer,
            body="I should not enter this conversation.",
        )
        with self.assertRaises(ValidationError):
            outsider_message.full_clean()

        blank_message = Message(
            conversation=self.conversation,
            sender=self.buyer,
            body="   ",
        )
        with self.assertRaises(ValidationError):
            blank_message.full_clean()

    def test_buyer_can_send_image_without_text_and_notification_is_generic(self):
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("marketplace:conversation", args=[self.conversation.pk]),
            {"body": "", "image_attachment": self.goat_photo("recent-goat.png")},
        )

        self.assertRedirects(
            response, reverse("marketplace:conversation", args=[self.conversation.pk])
        )
        message = Message.objects.get(conversation=self.conversation)
        self.assertTrue(message.image_attachment.name.endswith(".png"))
        self.assertNotIn("recent-goat", message.image_attachment.name)
        self.assertEqual(message.image_original_name, "recent-goat.png")
        notification = MarketplaceNotification.objects.get(
            dedup_key=f"message:{message.pk}"
        )
        self.assertEqual(notification.message, "Image attached.")

    def test_seller_can_send_image(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("marketplace:conversation", args=[self.conversation.pk]),
            {"body": "", "image_attachment": self.goat_photo("seller-view.png")},
        )

        self.assertEqual(response.status_code, 302)
        message = Message.objects.get(conversation=self.conversation)
        self.assertEqual(message.sender, self.admin)
        self.assertTrue(message.image_attachment)

    def test_message_can_include_text_and_image_and_renders_both(self):
        self.client.force_login(self.buyer)
        self.client.post(
            reverse("marketplace:conversation", args=[self.conversation.pk]),
            {
                "body": "Here is the condition I mean.",
                "image_attachment": self.goat_photo("condition.png"),
            },
        )
        message = Message.objects.get(conversation=self.conversation)

        response = self.client.get(
            reverse("marketplace:conversation", args=[self.conversation.pk])
        )

        self.assertContains(response, "Here is the condition I mean.")
        self.assertContains(
            response, reverse("marketplace:inquiry_image", args=[message.pk])
        )
        self.assertContains(response, "data-image-viewer")
        self.assertContains(response, "data-remove-image")
        self.assertContains(response, "Uploading image")

    def test_unsupported_inquiry_attachment_is_rejected(self):
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("marketplace:conversation", args=[self.conversation.pk]),
            {
                "body": "Unsafe attachment",
                "image_attachment": SimpleUploadedFile(
                    "payload.svg",
                    b"<svg><script>alert(1)</script></svg>",
                    content_type="image/svg+xml",
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid JPG, PNG, or WebP image.")
        self.assertFalse(Message.objects.filter(conversation=self.conversation).exists())

    def test_oversized_inquiry_image_has_clear_error(self):
        self.client.force_login(self.buyer)
        oversized = SimpleUploadedFile(
            "too-large.png",
            b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024),
            content_type="image/png",
        )

        response = self.client.post(
            reverse("marketplace:conversation", args=[self.conversation.pk]),
            {"body": "", "image_attachment": oversized},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Image is too large. Please select a smaller image."
        )
        self.assertFalse(Message.objects.filter(conversation=self.conversation).exists())

    def test_only_conversation_participants_can_fetch_inquiry_image(self):
        message = Message.objects.create(
            conversation=self.conversation,
            sender=self.buyer,
            body="Private image",
            image_attachment=self.goat_photo("private.png"),
            image_original_name="private.png",
            image_content_type="image/png",
            image_size=68,
        )
        image_url = reverse("marketplace:inquiry_image", args=[message.pk])

        self.client.force_login(self.other_buyer)
        self.assertEqual(self.client.get(image_url).status_code, 403)
        self.client.force_login(self.buyer)
        allowed = self.client.get(image_url)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed["X-Content-Type-Options"], "nosniff")
        self.assertEqual(allowed["Cache-Control"], "private, no-store")

    def test_deleting_message_removes_its_private_image(self):
        message = Message.objects.create(
            conversation=self.conversation,
            sender=self.buyer,
            body="Temporary photo",
            image_attachment=self.goat_photo("temporary.png"),
            image_original_name="temporary.png",
            image_content_type="image/png",
            image_size=68,
        )
        storage = message.image_attachment.storage
        stored_name = message.image_attachment.name
        self.assertTrue(storage.exists(stored_name))

        message.delete()

        self.assertFalse(storage.exists(stored_name))

    def test_storage_failure_keeps_conversation_working_and_allows_retry(self):
        self.client.force_login(self.buyer)
        storage = Message._meta.get_field("image_attachment").storage

        with patch.object(storage, "_save", side_effect=OSError("storage offline")):
            response = self.client.post(
                reverse("marketplace:conversation", args=[self.conversation.pk]),
                {"body": "Retry me", "image_attachment": self.goat_photo("retry.png")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "The image could not be uploaded. Please try again."
        )
        self.assertFalse(Message.objects.filter(conversation=self.conversation).exists())
        retry = self.client.post(
            reverse("marketplace:conversation", args=[self.conversation.pk]),
            {"body": "Retry worked", "image_attachment": self.goat_photo("retry.png")},
        )
        self.assertEqual(retry.status_code, 302)

    def test_conversation_model_rejects_listing_seller_as_buyer(self):
        invalid = Conversation(listing=self.listing, buyer=self.admin)

        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_closed_conversation_blocks_messages_until_reopened(self):
        self.client.force_login(self.buyer)
        status_url = reverse(
            "marketplace:conversation_status", args=[self.conversation.pk]
        )
        chat_url = reverse("marketplace:conversation", args=[self.conversation.pk])

        self.client.post(status_url, {"action": "close"})
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status, Conversation.CLOSED)
        self.assertEqual(self.conversation.closed_by, self.buyer)

        blocked = self.client.post(chat_url, {"body": "This must be blocked."})
        self.assertEqual(blocked.status_code, 200)
        self.assertFalse(self.conversation.messages.exists())

        self.client.post(status_url, {"action": "reopen"})
        self.client.post(chat_url, {"body": "Messaging is available again."})
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status, Conversation.OPEN)
        self.assertIsNone(self.conversation.closed_by)
        self.assertEqual(self.conversation.messages.count(), 1)

    def test_suspended_seller_cannot_open_seller_inbox_or_direct_chat(self):
        profile = self.approve_seller(self.other_buyer, "Suspended Messages Farm")
        listing = self.community_listing(self.other_buyer, "CM-SUSPENDED-CHAT")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        profile.status = SellerProfile.SUSPENDED
        profile.save(update_fields=["status"])
        self.client.force_login(self.other_buyer)

        self.assertRedirects(
            self.client.get(reverse("marketplace:seller_messages")),
            reverse("marketplace:seller_application"),
        )
        self.assertRedirects(
            self.client.get(
                reverse("marketplace:conversation", args=[conversation.pk])
            ),
            reverse("marketplace:seller_application"),
        )

    def test_message_form_enforces_two_thousand_character_limit(self):
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("marketplace:conversation", args=[self.conversation.pk]),
            {"body": "x" * 2001},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.conversation.messages.exists())
        self.assertContains(response, "Ensure this value has at most 2000 characters")

    def test_inquiry_is_routed_to_the_listing_owner(self):
        self.approve_seller(self.other_buyer, "Correct Seller")
        listing = self.community_listing(self.other_buyer, "CM-ROUTED")
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("marketplace:start_inquiry", args=[listing.pk])
        )

        conversation = Conversation.objects.get(listing=listing, buyer=self.buyer)
        self.assertRedirects(
            response, reverse("marketplace:conversation", args=[conversation.pk])
        )
        self.assertEqual(conversation.listing.seller, self.other_buyer)

    def test_direct_inquiry_url_rejects_nonapproved_seller_listing(self):
        profile = self.approve_seller(self.other_buyer, "Hidden Seller")
        listing = self.community_listing(self.other_buyer, "CM-HIDDEN-INQUIRY")
        profile.status = SellerProfile.SUSPENDED
        profile.save(update_fields=["status"])
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse("marketplace:start_inquiry", args=[listing.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            Conversation.objects.filter(listing=listing, buyer=self.buyer).exists()
        )

    def test_buyer_cannot_accept_or_complete_own_reservation(self):
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )

        with self.assertRaises(PermissionDenied):
            accept_reservation(reservation.pk, self.buyer)

        accept_reservation(reservation.pk, self.admin)
        with self.assertRaises(PermissionDenied):
            complete_sale(reservation.pk, self.buyer)

    def test_same_buyer_cannot_create_duplicate_active_request(self):
        request_reservation(self.listing.pk, self.buyer, self.conversation)

        with self.assertRaises(ValidationError):
            request_reservation(self.listing.pk, self.buyer, self.conversation)

        self.assertEqual(
            Reservation.objects.filter(
                listing=self.listing,
                buyer=self.buyer,
                status=Reservation.PENDING,
            ).count(),
            1,
        )

    def test_rejected_request_does_not_block_listing(self):
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )

        reject_reservation(reservation.pk, self.admin, "Pickup distance is too far.")

        reservation.refresh_from_db()
        self.listing.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.REJECTED)
        self.assertEqual(reservation.rejection_reason, "Pickup distance is too far.")
        self.assertEqual(self.listing.status, MarketplaceListing.AVAILABLE)

    def test_seller_b_cannot_manage_seller_a_reservation(self):
        seller_b = User.objects.create_user("reservation-seller-b")
        self.approve_seller(seller_b, "Reservation Seller B")
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )

        with self.assertRaises(PermissionDenied):
            accept_reservation(reservation.pk, seller_b)
        with self.assertRaises(PermissionDenied):
            reject_reservation(reservation.pk, seller_b)

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.PENDING)

    def test_suspended_seller_cannot_accept_request(self):
        seller = User.objects.create_user("reservation-suspended")
        profile = self.approve_seller(seller, "Suspended Reservation Farm")
        listing = self.community_listing(seller, "CM-SUSPENDED-RESERVE")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        reservation = request_reservation(listing.pk, self.buyer, conversation)
        profile.status = SellerProfile.SUSPENDED
        profile.save(update_fields=["status"])

        with self.assertRaises(PermissionDenied):
            accept_reservation(reservation.pk, seller)

    def test_expired_hold_atomically_returns_listing_to_available(self):
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )
        accept_reservation(reservation.pk, self.admin)
        Reservation.objects.filter(pk=reservation.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        self.assertEqual(expire_due_reservations(), 1)

        reservation.refresh_from_db()
        self.listing.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.EXPIRED)
        self.assertEqual(self.listing.status, MarketplaceListing.AVAILABLE)

    def test_pickup_proposal_requires_confirmation_by_other_participant(self):
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )
        accept_reservation(reservation.pk, self.admin)
        proposed = timezone.now() + timedelta(days=2)
        request_pickup(reservation.pk, self.buyer, proposed, "Buyer proposal")

        with self.assertRaises(PermissionDenied):
            confirm_pickup(reservation.pk, self.buyer)
        confirm_pickup(reservation.pk, self.admin)

        alternative = timezone.now() + timedelta(days=3)
        suggest_pickup(
            reservation.pk,
            self.admin,
            alternative,
            "Seller alternative",
            "Private pickup gate",
        )
        with self.assertRaises(PermissionDenied):
            confirm_pickup(reservation.pk, self.admin)
        confirm_pickup(reservation.pk, self.buyer)

        reservation.refresh_from_db()
        self.assertEqual(reservation.pickup_status, Reservation.PICKUP_CONFIRMED)
        self.assertEqual(reservation.pickup_confirmed_by, self.buyer)
        self.assertEqual(reservation.pickup_location, "Private pickup gate")

    def test_pending_request_cannot_schedule_pickup(self):
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )

        with self.assertRaises(ValidationError):
            request_pickup(
                reservation.pk,
                self.buyer,
                timezone.now() + timedelta(days=1),
            )

    def test_buyer_and_seller_reservation_pages_are_ownership_scoped(self):
        seller = User.objects.create_user("scoped-reservation-seller")
        self.approve_seller(seller, "Scoped Reservation Farm")
        listing = self.community_listing(seller, "CM-SCOPED-RES")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        reservation = request_reservation(listing.pk, self.buyer, conversation)

        self.client.force_login(self.buyer)
        buyer_page = self.client.get(reverse("marketplace:buyer_reservations"))
        self.assertContains(buyer_page, "CM-SCOPED-RES")
        self.client.force_login(self.other_buyer)
        other_page = self.client.get(reverse("marketplace:buyer_reservations"))
        self.assertNotContains(other_page, "CM-SCOPED-RES")

        self.client.force_login(seller)
        seller_page = self.client.get(reverse("marketplace:seller_reservations"))
        self.assertContains(seller_page, "CM-SCOPED-RES")
        self.assertContains(seller_page, "Accept and reserve goat")
        self.assertEqual(reservation.status, Reservation.PENDING)

    def test_reservation_action_endpoint_enforces_listing_seller(self):
        seller = User.objects.create_user("action-owner")
        outsider = User.objects.create_user("action-outsider")
        self.approve_seller(seller, "Action Owner Farm")
        self.approve_seller(outsider, "Outsider Farm")
        listing = self.community_listing(seller, "CM-ACTION-OWNER")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        reservation = request_reservation(listing.pk, self.buyer, conversation)
        self.client.force_login(outsider)

        response = self.client.post(
            reverse(
                "marketplace:buyer_seller_reservation_action",
                args=[reservation.pk],
            ),
            {"action": "accept"},
        )

        self.assertEqual(response.status_code, 403)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.PENDING)

    def test_admin_cannot_process_community_reservation_as_listing_seller(self):
        seller = User.objects.create_user("community-action-owner")
        self.approve_seller(seller, "Community Action Owner")
        listing = self.community_listing(seller, "CM-ADMIN-NOT-OWNER")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        reservation = request_reservation(listing.pk, self.buyer, conversation)
        self.client.force_login(self.admin)
        action_url = reverse(
            "marketplace:buyer_seller_reservation_action",
            args=[reservation.pk],
        )

        response = self.client.post(action_url, {"action": "accept"})

        self.assertEqual(response.status_code, 403)
        reservation.refresh_from_db()
        listing.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.PENDING)
        self.assertEqual(listing.status, MarketplaceListing.AVAILABLE)

        seller_page = self.client.get(reverse("marketplace:seller_reservations"))
        self.assertNotContains(seller_page, "CM-ADMIN-NOT-OWNER")

    def test_admin_can_only_cancel_community_reservation_through_moderation_endpoint(self):
        seller = User.objects.create_user("moderated-community-owner")
        self.approve_seller(seller, "Moderated Community Owner")
        listing = self.community_listing(seller, "CM-ADMIN-MODERATION")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        reservation = request_reservation(listing.pk, self.buyer, conversation)
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("marketplace:reservation_action", args=[reservation.pk]),
            {"action": "cancel", "reason": "Confirmed moderation issue."},
            follow=True,
        )

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.CANCELLED)
        self.assertEqual(reservation.cancelled_by, self.admin)
        self.assertContains(response, "cancelled by marketplace moderation")

    def test_accepted_reservation_exposes_private_pickup_only_to_buyer_and_seller(self):
        seller = User.objects.create_user("private-pickup-seller")
        self.approve_seller(seller, "Private Pickup Farm")
        listing = self.community_listing(seller, "CM-PRIVATE-PICKUP")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)
        reservation = request_reservation(listing.pk, self.buyer, conversation)
        accept_reservation(
            reservation.pk,
            seller,
            pickup_location="Confidential gate beside the water tower",
        )

        self.client.force_login(self.buyer)
        self.assertContains(
            self.client.get(reverse("marketplace:buyer_reservations")),
            "Confidential gate beside the water tower",
        )
        self.client.force_login(self.other_buyer)
        self.assertNotContains(
            self.client.get(reverse("marketplace:buyer_reservations")),
            "Confidential gate beside the water tower",
        )

    def test_complete_buyer_seller_reservation_flow_through_views(self):
        seller = User.objects.create_user(
            "flow-seller", password="testpass123"
        )
        self.approve_seller(seller, "Flow Seller Farm")
        listing = self.community_listing(seller, "CM-FULL-FLOW")
        conversation = Conversation.objects.create(listing=listing, buyer=self.buyer)

        self.client.force_login(self.buyer)
        request_response = self.client.post(
            reverse("marketplace:confirm_purchase", args=[conversation.pk])
        )
        self.assertRedirects(
            request_response, reverse("marketplace:buyer_reservations")
        )
        reservation = Reservation.objects.get(
            listing=listing, buyer=self.buyer
        )
        listing.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.PENDING)
        self.assertEqual(listing.status, MarketplaceListing.AVAILABLE)

        self.client.force_login(seller)
        action_url = reverse(
            "marketplace:buyer_seller_reservation_action",
            args=[reservation.pk],
        )
        self.client.post(
            action_url,
            {
                "action": "accept",
                "expires_at": "",
                "pickup_location": "Private community pickup point",
            },
        )
        reservation.refresh_from_db()
        listing.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.ACCEPTED)
        self.assertEqual(listing.status, MarketplaceListing.RESERVED)

        pickup_time = timezone.localtime() + timedelta(days=2)
        self.client.force_login(self.buyer)
        self.client.post(
            reverse("marketplace:pickup", args=[reservation.pk]),
            {
                "pickup_datetime": pickup_time.strftime("%Y-%m-%dT%H:%M"),
                "pickup_notes": "Buyer pickup proposal",
            },
        )
        reservation.refresh_from_db()
        self.assertEqual(
            reservation.pickup_status, Reservation.PICKUP_REQUESTED
        )

        self.client.force_login(seller)
        self.client.post(action_url, {"action": "confirm_pickup"})
        reservation.refresh_from_db()
        self.assertEqual(
            reservation.pickup_status, Reservation.PICKUP_CONFIRMED
        )
        self.client.post(action_url, {"action": "complete"})

        reservation.refresh_from_db()
        listing.refresh_from_db()
        listing.goat.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.COMPLETED)
        self.assertEqual(listing.status, MarketplaceListing.SOLD)
        self.assertEqual(listing.goat.status, "sold")
        self.assertFalse(listing.goat.is_active)

    def test_favorite_toggle_is_unique_and_reversible(self):
        self.client.force_login(self.buyer)
        url = reverse("marketplace:toggle_favorite", args=[self.listing.pk])

        self.client.post(url, {"next": reverse("marketplace:list")})
        self.assertEqual(
            Favorite.objects.filter(user=self.buyer, listing=self.listing).count(),
            1,
        )
        saved_page = self.client.get(reverse("marketplace:saved_goats"))
        self.assertContains(saved_page, "GT-MKT-001")

        self.client.post(url, {"next": reverse("marketplace:saved_goats")})
        self.assertFalse(
            Favorite.objects.filter(user=self.buyer, listing=self.listing).exists()
        )

    def test_saved_goats_are_private_and_keep_sold_status(self):
        Favorite.objects.create(user=self.buyer, listing=self.listing)
        self.listing.status = MarketplaceListing.SOLD
        self.listing.sold_at = timezone.now()
        self.listing.save(update_fields=["status", "sold_at"])

        self.client.force_login(self.buyer)
        own_page = self.client.get(reverse("marketplace:saved_goats"))
        self.assertContains(own_page, "GT-MKT-001")
        self.assertContains(own_page, "Sold")

        self.client.force_login(self.other_buyer)
        other_page = self.client.get(reverse("marketplace:saved_goats"))
        self.assertNotContains(other_page, "GT-MKT-001")

    def test_seller_cannot_favorite_or_report_own_listing(self):
        self.client.force_login(self.admin)

        self.client.post(
            reverse("marketplace:toggle_favorite", args=[self.listing.pk])
        )
        self.assertFalse(
            Favorite.objects.filter(user=self.admin, listing=self.listing).exists()
        )
        response = self.client.get(
            reverse("marketplace:report_listing", args=[self.listing.pk])
        )
        self.assertRedirects(
            response, reverse("marketplace:detail", args=[self.listing.pk])
        )

    def test_listing_report_is_duplicate_safe_and_notifies_staff(self):
        self.client.force_login(self.buyer)
        url = reverse("marketplace:report_listing", args=[self.listing.pk])
        payload = {
            "reason": MarketplaceReport.INCORRECT,
            "description": "The displayed weight appears incorrect.",
        }

        first = self.client.post(url, payload)
        second = self.client.post(url, payload)

        self.assertRedirects(
            first, reverse("marketplace:detail", args=[self.listing.pk])
        )
        self.assertRedirects(
            second, reverse("marketplace:detail", args=[self.listing.pk])
        )
        report = MarketplaceReport.objects.get(
            reporter=self.buyer, listing=self.listing
        )
        self.assertEqual(report.status, MarketplaceReport.PENDING)
        self.assertEqual(
            MarketplaceNotification.objects.filter(
                recipient=self.admin,
                report=report,
                notification_type=MarketplaceNotification.REPORT,
            ).count(),
            1,
        )

    def test_admin_can_review_and_hide_available_reported_listing(self):
        report = MarketplaceReport.objects.create(
            reporter=self.buyer,
            listing=self.listing,
            reason=MarketplaceReport.SUSPICIOUS,
            description="Please review this listing.",
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("marketplace:admin_report_action", args=[report.pk]),
            {"action": "hide", "notes": "Hidden pending seller clarification."},
        )

        self.assertRedirects(response, reverse("marketplace:admin_reports"))
        report.refresh_from_db()
        self.listing.refresh_from_db()
        self.assertEqual(report.status, MarketplaceReport.RESOLVED)
        self.assertEqual(self.listing.status, MarketplaceListing.DRAFT)
        self.assertTrue(
            MarketplaceNotification.objects.filter(
                recipient=self.buyer, report=report
            ).exists()
        )

    def test_admin_cannot_hide_listing_with_active_reservation(self):
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )
        accept_reservation(reservation.pk, self.admin)
        report = MarketplaceReport.objects.create(
            reporter=self.other_buyer,
            listing=self.listing,
            reason=MarketplaceReport.UNAVAILABLE,
        )
        self.client.force_login(self.admin)

        self.client.post(
            reverse("marketplace:admin_report_action", args=[report.pk]),
            {"action": "hide", "notes": "Attempted hide"},
        )

        self.listing.refresh_from_db()
        report.refresh_from_db()
        self.assertEqual(self.listing.status, MarketplaceListing.RESERVED)
        self.assertEqual(report.status, MarketplaceReport.PENDING)

    def test_notification_inbox_is_recipient_scoped(self):
        buyer_notification = MarketplaceNotification.objects.create(
            recipient=self.buyer,
            notification_type=MarketplaceNotification.LISTING,
            title="Buyer private update",
            listing=self.listing,
        )
        other_notification = MarketplaceNotification.objects.create(
            recipient=self.other_buyer,
            notification_type=MarketplaceNotification.LISTING,
            title="Other buyer private update",
            listing=self.listing,
        )
        self.client.force_login(self.buyer)

        inbox = self.client.get(reverse("marketplace:notifications"))
        self.assertContains(inbox, "Buyer private update")
        self.assertNotContains(inbox, "Other buyer private update")
        denied = self.client.post(
            reverse("marketplace:notification_open", args=[other_notification.pk])
        )
        self.assertEqual(denied.status_code, 404)
        self.client.post(
            reverse("marketplace:notification_open", args=[buyer_notification.pk])
        )
        buyer_notification.refresh_from_db()
        self.assertTrue(buyer_notification.is_read)

    def test_new_message_notifies_only_other_conversation_participant(self):
        self.client.force_login(self.buyer)

        self.client.post(
            reverse("marketplace:conversation", args=[self.conversation.pk]),
            {"body": "Is Saturday pickup possible?"},
        )

        notification = MarketplaceNotification.objects.get(
            dedup_key=f"message:{Message.objects.latest('pk').pk}"
        )
        self.assertEqual(notification.recipient, self.admin)
        self.assertEqual(notification.actor, self.buyer)
        self.assertEqual(notification.conversation, self.conversation)
        self.assertFalse(
            MarketplaceNotification.objects.filter(
                recipient=self.buyer,
                conversation=self.conversation,
                notification_type=MarketplaceNotification.MESSAGE,
            ).exists()
        )

    def test_marketplace_notification_deduplication(self):
        values = {
            "recipient": self.buyer,
            "notification_type": MarketplaceNotification.LISTING,
            "title": "One event",
            "listing": self.listing,
            "dedup_key": "test-event-one",
        }
        first, first_created = create_marketplace_notification(**values)
        second, second_created = create_marketplace_notification(**values)

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            MarketplaceNotification.objects.filter(
                dedup_key="test-event-one"
            ).count(),
            1,
        )

    def test_marketplace_events_do_not_create_security_alerts_or_sms(self):
        security_before = SecurityNotification.objects.count()
        sms_before = SmsLog.objects.count()
        self.conversation.delete()
        self.client.force_login(self.buyer)

        self.client.post(
            reverse("marketplace:start_inquiry", args=[self.listing.pk])
        )

        self.assertEqual(SecurityNotification.objects.count(), security_before)
        self.assertEqual(SmsLog.objects.count(), sms_before)
        self.assertTrue(
            MarketplaceNotification.objects.filter(
                recipient=self.admin,
                notification_type=MarketplaceNotification.INQUIRY,
            ).exists()
        )

    def test_draft_listing_cannot_be_favorited_or_reported_by_guessed_id(self):
        self.listing.status = MarketplaceListing.DRAFT
        self.listing.save(update_fields=["status"])
        self.client.force_login(self.buyer)

        self.assertEqual(
            self.client.post(
                reverse("marketplace:toggle_favorite", args=[self.listing.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("marketplace:report_listing", args=[self.listing.pk])
            ).status_code,
            404,
        )

    def test_saved_goat_followers_are_notified_when_listing_is_sold(self):
        Favorite.objects.create(user=self.other_buyer, listing=self.listing)
        reservation = request_reservation(
            self.listing.pk, self.buyer, self.conversation
        )
        accept_reservation(reservation.pk, self.admin)
        request_pickup(
            reservation.pk,
            self.buyer,
            timezone.now() + timedelta(days=1),
        )
        confirm_pickup(reservation.pk, self.admin)

        complete_sale(reservation.pk, self.admin)

        self.assertTrue(
            MarketplaceNotification.objects.filter(
                recipient=self.other_buyer,
                listing=self.listing,
                notification_type=MarketplaceNotification.LISTING,
                title__icontains="sold",
            ).exists()
        )
        self.assertFalse(
            MarketplaceNotification.objects.filter(
                recipient=self.buyer,
                listing=self.listing,
                notification_type=MarketplaceNotification.LISTING,
                title__icontains="sold",
            ).exists()
        )
