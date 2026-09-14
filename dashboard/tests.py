import re
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings

from marketplace.auth import FARM_OWNER_GROUP_NAME


class RootLandingTests(TestCase):
    def test_public_visitor_is_sent_to_marketplace(self):
        response = self.client.get("/")

        self.assertRedirects(
            response,
            "/marketplace/",
            fetch_redirect_response=False,
        )

    def test_marketplace_user_is_sent_to_marketplace(self):
        user = get_user_model().objects.create_user(
            username="marketplace-user",
            password="test-pass",
        )
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertRedirects(
            response,
            "/marketplace/",
            fetch_redirect_response=False,
        )

    def test_staff_user_is_sent_to_admin_dashboard(self):
        user = get_user_model().objects.create_user(
            username="staff-user",
            password="test-pass",
            is_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertRedirects(response, "/iot/", fetch_redirect_response=False)

    def test_farm_owner_is_sent_to_owner_dashboard(self):
        user = get_user_model().objects.create_user(
            username="farm-owner",
            password="test-pass",
        )
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        user.groups.add(owner_group)
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertRedirects(
            response,
            "/iot/owner/",
            fetch_redirect_response=False,
        )


class PwaSecurityTests(TestCase):
    def test_service_worker_is_root_scoped_and_not_cached(self):
        response = self.client.get('/service-worker.js')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertIn('no-store', response['Cache-Control'])
        body = b''.join(response.streaming_content).decode()
        self.assertIn('startsWith("/static/")', body)
        for private_prefix in ('/admin/', '/accounts/', '/iot/', '/sms/'):
            self.assertNotIn(f'cache.put("{private_prefix}', body)

    def test_manifest_is_installable_and_uses_safe_start_url(self):
        manifest_path = finders.find('manifest.webmanifest')
        self.assertIsNotNone(manifest_path)
        with open(manifest_path, encoding='utf-8') as manifest_file:
            manifest = json.load(manifest_file)
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual(manifest['scope'], '/')
        self.assertTrue(manifest['start_url'].startswith('/marketplace/'))
        self.assertEqual({icon['sizes'] for icon in manifest['icons']}, {'192x192', '512x512'})


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AccountRecoveryTests(TestCase):
    def setUp(self):
        self.password = 'Strong-test-password-932!'
        self.user = get_user_model().objects.create_user(
            username='recovery-user',
            email='recovery@example.com',
            password=self.password,
        )
        from allauth.account.models import EmailAddress
        EmailAddress.objects.create(
            user=self.user,
            email=self.user.email,
            primary=True,
            verified=True,
        )

    def test_reset_pages_use_gohmotech_account_layout(self):
        response = self.client.get('/accounts/password/reset/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Secure account center')
        self.assertContains(response, 'does not store these pages for offline use')

    def test_password_reset_token_is_single_use(self):
        response = self.client.post(
            '/accounts/password/reset/',
            {'email': self.user.email},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r'https?://[^\s]+(/accounts/password/reset/key/[^\s]+/)', mail.outbox[0].body)
        self.assertIsNotNone(match)
        original_path = match.group(1)

        token_page = self.client.get(original_path, follow=True)
        self.assertEqual(token_page.status_code, 200)
        reset_path = token_page.redirect_chain[-1][0] if token_page.redirect_chain else original_path
        response = self.client.post(
            reset_path,
            {'password1': 'Replacement-password-741!', 'password2': 'Replacement-password-741!'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Replacement-password-741!'))

        self.client.logout()
        replay = self.client.get(original_path, follow=True)
        self.assertEqual(replay.status_code, 200)
        self.assertContains(replay, 'invalid', status_code=200)
