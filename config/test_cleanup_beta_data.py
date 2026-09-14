import io
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from iot.models import Goat
from sms.models import SmsLog


@override_settings(DEBUG=False)
class CleanupBetaDataCommandTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("production-admin", is_staff=True)
        self.owner = User.objects.create_user("production-owner")
        self.owner.groups.add(Group.objects.get_or_create(name="Farm Owners")[0])
        self.beta_user = User.objects.create_user("beta-user")
        self.goat = Goat.all_objects.create(
            goat_id="CM-TEST-1",
            name="Synthetic",
            breed="native",
            gender="female",
            owner=self.beta_user,
            record_source="community",
        )
        SmsLog.objects.create(
            sms_type="test", recipient="redacted", message="test",
            status="sent", provider="console",
        )

    def run_dry(self):
        output = io.StringIO()
        database_name = str(settings.DATABASES["default"]["NAME"])
        with patch.dict("os.environ", {"DJANGO_SETTINGS_MODULE": "config.beta"}), patch(
            "iot.management.commands.cleanup_beta_data.EXPECTED_DATABASE",
            database_name,
        ):
            call_command("cleanup_beta_data", dry_run=True, stdout=output)
        return output.getvalue()

    def test_dry_run_is_non_mutating_and_preserves_privileged_accounts(self):
        before = {
            "users": User.objects.count(),
            "goats": Goat.all_objects.count(),
            "sms": SmsLog.objects.count(),
        }
        output = self.run_dry()
        after = {
            "users": User.objects.count(),
            "goats": Goat.all_objects.count(),
            "sms": SmsLog.objects.count(),
        }
        self.assertEqual(before, after)
        self.assertIn("BETA CLEANUP DRY RUN — ZERO DATABASE CHANGES", output)
        self.assertIn("username=production-admin", output)
        self.assertIn("username=production-owner", output)
        self.assertIn("username=beta-user", output)
        self.assertIn("iot.Goat: 1", output)
        self.assertIn("sms.SmsLog: 1", output)

    def test_confirm_requires_plan_hash_backup_and_quarantine(self):
        database_name = str(settings.DATABASES["default"]["NAME"])
        with patch.dict("os.environ", {"DJANGO_SETTINGS_MODULE": "config.beta"}), patch(
            "iot.management.commands.cleanup_beta_data.EXPECTED_DATABASE",
            database_name,
        ):
            with self.assertRaises(CommandError):
                call_command("cleanup_beta_data", confirm=True)
