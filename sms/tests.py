from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from datetime import datetime, time, timezone as dt_timezone
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from marketplace.auth import FARM_OWNER_GROUP_NAME
from marketplace.forms import MarketplaceSignupForm
from iot.models import Device, SensorReading
from security.models import Notification

from .forms import SmsRegistrationForm
from .models import (DailySummaryRun, SmsLog, SmsRegistration, SmsReminder,
                     SmsSettings)
from .services import send_sms
from .summaries import build_daily_summary_text
from .tasks import send_daily_summary
from .tasks import send_alert_sms
from .tasks import send_due_reminders


class SmsRegistrationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('owner', password='test-password')
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        self.owner.groups.add(owner_group)
        self.client_user = User.objects.create_user(
            'buyer', email='buyer@example.com', password='test-password'
        )

    def test_login_is_required(self):
        response = self.client.get(reverse('sms:registration'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_owner_can_register_and_normalize_number(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('sms:registration'),
            {'phone_number': '+63 917-123-4567', 'is_active': 'on'},
        )

        self.assertRedirects(response, reverse('sms:registration'))
        registration = SmsRegistration.objects.get(user=self.owner)
        self.assertEqual(registration.phone_number, '09171234567')
        self.assertTrue(registration.is_active)
        self.assertFalse(registration.receives_farm_alerts)

    def test_account_owner_cannot_enable_farm_alert_delivery(self):
        self.client.force_login(self.owner)

        self.client.post(
            reverse('sms:registration'),
            {
                'phone_number': '09171234567',
                'is_active': 'on',
                'receives_farm_alerts': 'on',
            },
        )

        self.assertFalse(
            SmsRegistration.objects.get(user=self.owner).receives_farm_alerts
        )

    def test_only_admin_can_select_farm_alert_recipients(self):
        registration = SmsRegistration.objects.create(
            user=self.owner,
            phone_number='09171234567',
            is_active=True,
        )
        self.client.force_login(self.owner)
        owner_response = self.client.post(
            reverse('sms:alert_recipients'),
            {'recipient_ids': [registration.pk]},
        )
        self.assertEqual(owner_response.status_code, 403)

        admin = get_user_model().objects.create_user(
            'sms-admin', password='test-password', is_staff=True
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse('sms:alert_recipients'),
            {'recipient_ids': [registration.pk]},
        )

        self.assertRedirects(response, reverse('sms:dashboard'))
        registration.refresh_from_db()
        self.assertTrue(registration.receives_farm_alerts)

    def test_marketplace_client_can_open_and_pause_registration(self):
        registration = SmsRegistration.objects.create(
            user=self.client_user,
            phone_number='09171234567',
            is_active=True,
        )
        self.client.force_login(self.client_user)

        self.assertEqual(self.client.get(reverse('sms:registration')).status_code, 200)
        response = self.client.post(
            reverse('sms:registration'),
            {'phone_number': '09171234567'},
        )

        self.assertRedirects(response, reverse('sms:registration'))
        registration.refresh_from_db()
        self.assertFalse(registration.is_active)

    def test_client_slashless_registration_url_redirects_normally(self):
        self.client.force_login(self.client_user)
        response = self.client.get(reverse('sms:registration').rstrip('/'))
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.url, reverse('sms:registration'))

    def test_invalid_mobile_number_is_rejected(self):
        form = SmsRegistrationForm(
            data={'phone_number': '12345', 'is_active': True}
        )
        self.assertFalse(form.is_valid())
        self.assertIn('phone_number', form.errors)

    def test_marketplace_signup_can_create_sms_registration(self):
        User = get_user_model()
        user = User.objects.create_user('new-buyer', email='new@example.com')
        form = MarketplaceSignupForm(
            data={
                'first_name': 'New',
                'last_name': 'Buyer',
                'sms_phone_number': '917 555 1234',
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        form.signup(None, user)

        registration = SmsRegistration.objects.get(user=user)
        self.assertEqual(registration.phone_number, '09175551234')
        self.assertTrue(registration.is_active)


@override_settings(SMS_BACKEND='console')
class DailySummaryTests(TestCase):
    def setUp(self):
        self.config = SmsSettings.get_config()
        self.config.enabled = True
        self.config.daily_enabled = True
        self.config.daily_time = time(22, 0)
        self.config.recipient_number = '09171234567'
        self.config.save()
        self.due = datetime(2026, 10, 5, 14, 0, 3, tzinfo=dt_timezone.utc)

    @patch('sms.tasks.timezone.now')
    def test_executes_at_configured_manila_time_once(self, now):
        now.return_value = self.due
        self.assertEqual(send_daily_summary(), 'Daily summary: sent')
        self.assertIn('already sent', send_daily_summary())
        run = DailySummaryRun.objects.get(scheduled_date='2026-10-05')
        self.assertEqual(run.status, 'sent')
        self.assertEqual(SmsLog.objects.filter(sms_type='daily').count(), 1)
        self.assertEqual(timezone.localtime(run.scheduled_for).hour, 22)

    @patch('sms.tasks.timezone.now')
    def test_same_day_missed_run_is_caught_up_once(self, now):
        now.return_value = datetime(
            2026, 10, 5, 14, 15, tzinfo=dt_timezone.utc)
        self.assertEqual(send_daily_summary(), 'Daily summary: sent')
        self.assertEqual(SmsLog.objects.filter(sms_type='daily').count(), 1)

    @patch('sms.tasks.timezone.now')
    def test_before_schedule_does_not_create_run(self, now):
        now.return_value = datetime(
            2026, 10, 5, 13, 59, tzinfo=dt_timezone.utc)
        self.assertEqual(send_daily_summary(), 'Not due')
        self.assertFalse(DailySummaryRun.objects.exists())

    @patch('sms.tasks.timezone.now')
    def test_disabled_master_records_skipped_attempt(self, now):
        self.config.enabled = False
        self.config.save(update_fields=['enabled'])
        now.return_value = self.due
        self.assertIn('skipped', send_daily_summary())
        run = DailySummaryRun.objects.get()
        self.assertEqual(run.status, 'skipped')
        self.assertIn('master switch', run.error_message)

    def test_empty_day_and_unsupported_soil_are_handled(self):
        text = build_daily_summary_text(now=self.due)
        self.assertIn('Env: no readings', text)
        self.assertNotIn('soil', text.lower())

    def test_summary_uses_real_reading_from_local_day_without_soil(self):
        device = Device.objects.create(
            device_id='env-summary', name='Environment', device_type='sensor')
        reading = SensorReading.objects.create(
            device=device, temperature=28.5, humidity=75,
            soil_moisture=42)
        SensorReading.objects.filter(pk=reading.pk).update(received_at=self.due)

        text = build_daily_summary_text(now=self.due)

        self.assertIn('28.5C', text)
        self.assertIn('75%RH', text)
        self.assertNotIn('soil', text.lower())


class ScheduledReminderTests(TestCase):
    def setUp(self):
        config = SmsSettings.get_config()
        config.enabled = True
        config.reminders_enabled = True
        config.recipient_number = '09171234567'
        config.save()
        self.reminder = SmsReminder.objects.create(
            title='Morning feeding',
            reminder_type='feeding',
            message='Give each goat its measured ration.',
            schedule_time=time(8, 30),
        )

    @patch('sms.services.send_sms')
    @patch('sms.tasks.timezone.now')
    def test_due_reminder_includes_title_type_time_and_message(
            self, now, mocked_send):
        now.return_value = datetime(
            2026, 10, 5, 0, 30, 15, tzinfo=dt_timezone.utc)
        mocked_send.return_value = Mock(status='sent')

        result = send_due_reminders()

        self.assertEqual(result, 'Sent 1 reminder(s)')
        mocked_send.assert_called_once_with(
            message=(
                'Title: Morning feeding\n'
                'Type: Feeding\n'
                'Time: 08:30 AM\n'
                'Message: Give each goat its measured ration.'
            ),
            sms_type='reminder',
            reminder=self.reminder,
        )


class SmsFailureTests(TestCase):
    def setUp(self):
        config = SmsSettings.get_config()
        config.enabled = True
        config.alert_cooldown_minutes = 0
        config.recipient_number = '09171234567'
        config.save()

    @patch('sms.services.get_client')
    def test_provider_exception_is_recorded_and_does_not_escape(self, get_client):
        client = Mock(name='provider-client')
        client.name = 'broken'
        client.send.side_effect = RuntimeError('gateway offline')
        get_client.return_value = client

        log = send_sms(message='real alert', sms_type='alert')

        self.assertEqual(log.status, 'failed')
        self.assertIn('gateway offline', log.error_message)

    def test_missing_recipient_fails_safely(self):
        config = SmsSettings.get_config()
        config.recipient_number = ''
        config.save(update_fields=['recipient_number'])
        log = send_sms(message='test', sms_type='alert')
        self.assertEqual(log.status, 'failed')

    @patch('sms.services.send_sms')
    def test_eligible_alert_calls_sms_service(self, mocked_send):
        notification = Notification.objects.create(
            title='Sensor stopped reporting', severity='high',
            notification_type='device_anomaly', source='Environment')
        mocked_send.return_value = Mock(status='sent')

        result = send_alert_sms(notification.pk)

        self.assertEqual(result, 'Alert SMS: sent')
        mocked_send.assert_called_once()
        self.assertEqual(
            mocked_send.call_args.kwargs['notification'], notification)

    @patch('sms.services.send_sms')
    def test_alert_is_sent_to_each_admin_selected_registration(self, mocked_send):
        User = get_user_model()
        first = User.objects.create_user('first-recipient')
        second = User.objects.create_user('second-recipient')
        SmsRegistration.objects.create(
            user=first,
            phone_number='09171234567',
            is_active=True,
            receives_farm_alerts=True,
        )
        SmsRegistration.objects.create(
            user=second,
            phone_number='09175551234',
            is_active=True,
            receives_farm_alerts=True,
        )
        notification = Notification.objects.create(
            title='Goat is missing', severity='critical',
            notification_type='missing_goat', source='Barn camera')
        mocked_send.side_effect = [Mock(status='sent'), Mock(status='sent')]

        result = send_alert_sms(notification.pk)

        self.assertEqual(result, 'Alert SMS: 2 sent, 0 failed')
        self.assertEqual(mocked_send.call_count, 2)
        self.assertEqual(
            {call.kwargs['number'] for call in mocked_send.call_args_list},
            {'09171234567', '09175551234'},
        )
