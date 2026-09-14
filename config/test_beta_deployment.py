import tempfile
from pathlib import Path
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.auth.models import AnonymousUser, Group, User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from config.beta_access import PublicBetaAccessMiddleware
from config.websocket_access import FarmWebSocketAccess
from marketplace.auth import FARM_OPERATOR_GROUP_NAME, FARM_OWNER_GROUP_NAME, has_farm_access


class BetaAccessTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_user('beta-admin', is_staff=True)
        self.buyer = User.objects.create_user('beta-buyer')
        self.middleware = PublicBetaAccessMiddleware(lambda request: HttpResponse('allowed'))

    def check(self, path, user, method='get'):
        request = getattr(self.factory, method)(path)
        request.user = user
        return self.middleware(request).status_code

    def test_anonymous_hardware_routes_are_denied(self):
        for path in ('/iot/api/sensor-readings/', '/iot/api/scale/readings/',
                     '/feeding/api/logs/servo-confirm/', '/iot/api/actuators/esp32_sync_state/'):
            with self.subTest(path=path):
                self.assertEqual(self.check(path, AnonymousUser(), 'post'), 403)

    def test_buyer_cannot_read_farm_data(self):
        self.assertEqual(self.check('/iot/api/sensor-readings', self.buyer), 403)

    def test_admin_can_read_but_not_actuate_in_beta(self):
        self.assertEqual(self.check('/feeding/api/logs/', self.admin), 200)
        self.assertEqual(self.check('/feeding/api/logs/manual_feed/', self.admin, 'post'), 503)

    def test_marketplace_and_authenticated_receiver_views_keep_their_own_policy(self):
        self.assertEqual(self.check('/marketplace/goats/', AnonymousUser()), 200)
        self.assertEqual(self.check('/iot/api/ble/observations/', AnonymousUser(), 'post'), 200)
        # The real receiver view must still reject an uncredentialed request.
        self.assertEqual(self.client.post('/iot/api/ble/observations/', {}).status_code, 401)


@override_settings(ROOT_URLCONF='config.beta_urls')
class BetaMediaTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.temp.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.admin = User.objects.create_user('media-admin', is_staff=True)
        self.owner = User.objects.create_user('document-owner')
        self.other = User.objects.create_user('other-reader')

    def write_file(self, name):
        target = Path(self.temp.name) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'beta-test-file')

    def test_seller_document_requires_owner_or_staff(self):
        from marketplace.models import SellerProfile
        name = 'seller_documents/2026/09/private.pdf'
        self.write_file(name)
        SellerProfile.objects.create(user=self.owner, farm_name='Beta farm', supporting_document=name)
        url = '/media/' + name
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        for user in (self.owner, self.admin):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response['Cache-Control'])
            response.close()

    def test_only_published_goat_photos_are_public(self):
        from iot.models import Goat, GoatImage
        from marketplace.models import MarketplaceListing
        name = 'goat_images/2026/09/goat.jpg'
        self.write_file(name)
        goat = Goat.objects.create(goat_id='BETA-001', breed='native', gender='female')
        GoatImage.objects.create(goat=goat, image=name)
        listing = MarketplaceListing.objects.create(goat=goat, seller=self.admin, price='1000', sales_description='Beta')
        self.assertEqual(self.client.get('/media/' + name).status_code, 404)
        listing.status = MarketplaceListing.AVAILABLE
        listing.save()
        response = self.client.get('/media/' + name)
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_path_traversal_and_unregistered_files_are_not_public(self):
        self.write_file('unregistered.txt')
        self.assertEqual(self.client.get('/media/unregistered.txt').status_code, 404)
        self.assertEqual(self.client.get('/media/../beta.env').status_code, 404)


class FarmWebSocketTests(TransactionTestCase):
    def test_anonymous_buyer_and_inactive_staff_are_rejected(self):
        buyer = User.objects.create_user('ws-buyer')
        inactive = User.objects.create_user('ws-inactive', is_staff=True, is_active=False)
        self.assertFalse(has_farm_access(buyer))
        for user in (AnonymousUser(), inactive):
            async_to_sync(self.connect_as)(user, False)

    def test_active_staff_and_operator_can_connect(self):
        admin = User.objects.create_user('ws-admin', is_staff=True)
        operator = User.objects.create_user('ws-operator')
        operator.groups.add(Group.objects.get_or_create(name=FARM_OPERATOR_GROUP_NAME)[0])
        self.assertTrue(has_farm_access(operator))
        async_to_sync(self.connect_as)(admin, True)

    async def connect_as(self, user, expected):
        received = iter((
            {'type': 'websocket.connect'},
            {'type': 'websocket.disconnect'},
        ))
        sent = []

        async def receive():
            return next(received)

        async def send(message):
            sent.append(message)

        async def endpoint(scope, receive, send):
            await receive()
            await send({'type': 'websocket.accept'})
            await receive()

        def run_inline(function):
            async def wrapped(*args, **kwargs):
                return function(*args, **kwargs)
            return wrapped

        # Keep this middleware unit test on the test runner's DB thread. The
        # production wrapper remains database_sync_to_async; role queries are
        # separately asserted synchronously above.
        with patch('config.websocket_access.database_sync_to_async', run_inline):
            await FarmWebSocketAccess(endpoint)(
                {'type': 'websocket', 'path': '/ws/sensors/', 'user': user},
                receive,
                send,
            )
        if expected:
            self.assertEqual(sent, [{'type': 'websocket.accept'}])
        else:
            self.assertEqual(sent, [{'type': 'websocket.close', 'code': 4403}])


class DirectApiAuthorizationTests(TestCase):
    """Exercise view permissions directly so route middleware cannot mask defects."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.buyer = User.objects.create_user('direct-api-buyer')
        self.operator = User.objects.create_user('direct-api-operator')
        self.operator.groups.add(
            Group.objects.get_or_create(name=FARM_OPERATOR_GROUP_NAME)[0]
        )
        self.owner = User.objects.create_user('direct-api-owner')
        self.owner.groups.add(Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)[0])

    def test_marketplace_user_cannot_read_actuator_or_tracking_state(self):
        from iot.ble_api import BLETrackingSnapshotAPIView
        from iot.views import ActuatorStateViewSet

        request = self.factory.get('/iot/api/actuators/')
        force_authenticate(request, user=self.buyer)
        response = ActuatorStateViewSet.as_view({'get': 'list'})(request)
        self.assertEqual(response.status_code, 403)

        request = self.factory.get('/iot/api/ble/tracking/')
        force_authenticate(request, user=self.buyer)
        response = BLETrackingSnapshotAPIView.as_view()(request)
        self.assertEqual(response.status_code, 403)

    def test_operator_cannot_modify_actuator_state(self):
        from iot.views import ActuatorStateViewSet

        request = self.factory.post('/iot/api/actuators/', {}, format='json')
        force_authenticate(request, user=self.operator)
        response = ActuatorStateViewSet.as_view({'post': 'create'})(request)
        self.assertEqual(response.status_code, 403)

    def test_marketplace_user_cannot_read_sms_logs(self):
        from sms.views import SmsLogViewSet

        request = self.factory.get('/sms/api/logs/')
        force_authenticate(request, user=self.buyer)
        response = SmsLogViewSet.as_view({'get': 'list'})(request)
        self.assertEqual(response.status_code, 403)

    def test_browser_session_cannot_impersonate_feed_level_device(self):
        from feeding.views import FeedLevelViewSet

        request = self.factory.post(
            '/feeding/api/levels/update/',
            {'feeder_id': 99, 'percentage': 100, 'distance_cm': 2},
            format='json',
        )
        force_authenticate(request, user=self.owner)
        response = FeedLevelViewSet.as_view({'post': 'update_from_esp32'})(request)
        self.assertEqual(response.status_code, 403)

    def test_actuator_actor_comes_from_authenticated_session(self):
        from iot.models import ActuatorState, Device
        from iot.views import ActuatorStateViewSet

        device = Device.objects.create(
            device_id='direct-control-device',
            name='Direct control device',
            device_type='actuator',
        )
        actuator = ActuatorState.objects.create(device=device, actuator_type='door')
        request = self.factory.post(
            '/iot/api/actuators/1/control/',
            {'state': 'open', 'triggered_by': 'forged-admin-name'},
            format='json',
        )
        force_authenticate(request, user=self.owner)
        response = ActuatorStateViewSet.as_view({'post': 'control'})(request, pk=actuator.pk)

        self.assertEqual(response.status_code, 200)
        actuator.refresh_from_db()
        self.assertEqual(actuator.last_triggered_by, self.owner.username)

    def test_history_window_rejects_malformed_or_excessive_values(self):
        from iot.views import ActuationLogViewSet

        for value in ('not-a-number', '0', '999999'):
            request = self.factory.get('/iot/api/actuation-logs/stats/', {'hours': value})
            force_authenticate(request, user=self.owner)
            response = ActuationLogViewSet.as_view({'get': 'stats'})(request)
            self.assertEqual(response.status_code, 400, value)
