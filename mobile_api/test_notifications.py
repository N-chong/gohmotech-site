from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from marketplace.auth import FARM_OWNER_GROUP_NAME
from marketplace.models import MarketplaceNotification
from security.models import Notification as FarmNotification


class UnifiedMobileNotificationTests(APITestCase):
    def create_user(self, username, group_name=None):
        user = get_user_model().objects.create_user(
            username=username, password='safe-test-password'
        )
        if group_name:
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)
        return user

    def authenticate(self, user):
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

    def setUp(self):
        self.owner = self.create_user('notification-owner', FARM_OWNER_GROUP_NAME)
        self.marketplace_user = self.create_user('notification-marketplace-user')
        self.farm_alert = FarmNotification.objects.create(
            title='Camera disconnected',
            description='North pen camera is unavailable.',
            severity='high',
            notification_type='device_anomaly',
            source='North pen camera',
        )
        self.owner_message = MarketplaceNotification.objects.create(
            recipient=self.owner,
            notification_type=MarketplaceNotification.MESSAGE,
            title='New buyer message',
            message='Can I inspect the goat this weekend?',
        )
        MarketplaceNotification.objects.create(
            recipient=self.marketplace_user,
            notification_type=MarketplaceNotification.MESSAGE,
            title='Private notification for another account',
        )

    def test_farm_owner_receives_farm_and_own_seller_notifications(self):
        self.authenticate(self.owner)
        response = self.client.get('/api/mobile/notifications/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(
            {item['key'] for item in response.data['results']},
            {f'farm:{self.farm_alert.pk}', f'marketplace:{self.owner_message.pk}'},
        )
        self.assertEqual(response.data['unread_count'], 2)
        self.assertEqual(response.data['message_unread_count'], 1)
        self.assertEqual(response.data['facets'], {
            'all': 2,
            'alerts': 1,
            'messages': 1,
            'transactions': 0,
            'marketplace': 1,
        })

    def test_marketplace_only_account_cannot_open_owner_notification_center(self):
        self.authenticate(self.marketplace_user)

        self.assertEqual(self.client.get('/api/mobile/notifications/').status_code, 403)
        self.assertEqual(
            self.client.get('/api/mobile/notifications/summary/').status_code, 403
        )

    def test_owner_can_mark_individual_and_all_notifications_read(self):
        self.authenticate(self.owner)
        marked = self.client.post(
            f'/api/mobile/notifications/marketplace/{self.owner_message.pk}/', {},
            format='json',
        )
        read_all = self.client.post('/api/mobile/notifications/read-all/', {}, format='json')

        self.assertEqual(marked.status_code, 200)
        self.assertEqual(read_all.status_code, 200)
        self.owner_message.refresh_from_db()
        self.farm_alert.refresh_from_db()
        self.assertTrue(self.owner_message.is_read)
        self.assertTrue(self.farm_alert.is_read)

    def test_owner_cannot_mark_another_accounts_marketplace_notification(self):
        other_notice = MarketplaceNotification.objects.get(
            recipient=self.marketplace_user
        )
        self.authenticate(self.owner)
        response = self.client.post(
            f'/api/mobile/notifications/marketplace/{other_notice.pk}/', {},
            format='json',
        )

        self.assertEqual(response.status_code, 404)
        other_notice.refresh_from_db()
        self.assertFalse(other_notice.is_read)

    def test_message_filter_excludes_transactions_and_farm_alerts(self):
        MarketplaceNotification.objects.create(
            recipient=self.owner,
            notification_type=MarketplaceNotification.SALE,
            title='Sale completed',
        )
        self.authenticate(self.owner)
        response = self.client.get('/api/mobile/notifications/?filter=messages')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['category'], 'messages')
        self.assertEqual(response.data['facets']['all'], 3)
        self.assertEqual(response.data['facets']['messages'], 1)
        self.assertEqual(response.data['facets']['transactions'], 1)
