from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from feeding.models import FeedLevel, FeedLog
from iot.models import Device
from marketplace.auth import FARM_OWNER_GROUP_NAME


class ManualFeedingSafetyTests(APITestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username='feeding-owner', password='safe-test-password'
        )
        owner_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        user.groups.add(owner_group)
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        self.feeder = Device.objects.create(
            device_id='FEEDER-TEST-1', name='Test feeder', device_type='feeder'
        )
        self.level = FeedLevel.objects.create(
            feeder=self.feeder, current_level_grams=5000, capacity_grams=10000
        )
        self.url = '/feeding/api/logs/manual_feed/'

    def test_offline_feeder_rejects_command_without_changing_level(self):
        response = self.client.post(
            self.url, {'feeder_id': self.feeder.id, 'amount': 500}, format='json'
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'FEEDER_OFFLINE')
        self.assertFalse(FeedLog.objects.exists())
        self.level.refresh_from_db()
        self.assertEqual(self.level.current_level_grams, 5000)

    def test_invalid_amount_does_not_create_command_or_change_inventory(self):
        self.feeder.last_sensor_received_at = timezone.now()
        self.feeder.save(update_fields=['last_sensor_received_at'])

        response = self.client.post(
            self.url, {'feeder_id': self.feeder.id, 'amount': -500}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(FeedLog.objects.exists())
        self.level.refresh_from_db()
        self.assertEqual(self.level.current_level_grams, 5000)

    def test_online_feeder_creates_pending_command(self):
        self.feeder.last_sensor_received_at = timezone.now()
        self.feeder.save(update_fields=['last_sensor_received_at'])

        response = self.client.post(
            self.url, {'feeder_id': self.feeder.id, 'amount': 500}, format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['device_online'])
        self.assertEqual(response.data['confirmation'], 'pending_device_confirmation')
        self.assertEqual(FeedLog.objects.get().status, 'pending')
        self.level.refresh_from_db()
        self.assertEqual(self.level.current_level_grams, 4500)