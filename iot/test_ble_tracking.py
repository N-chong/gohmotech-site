from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from marketplace.auth import FARM_OPERATOR_GROUP_NAME

from .ble_services import build_tracking_snapshot, refresh_tracking_statuses
from .models import (
    BLEBeacon,
    BLEReceiver,
    BLETrackingSettings,
    BLETrackingState,
    Device,
    Goat,
)


class BLETrackingStatusTests(TestCase):
    UUID = 'E2C56DB5-DFFB-48D2-B060-D0F5A71096E0'

    def setUp(self):
        config = BLETrackingSettings.get_config()
        config.possibly_lost_timeout_seconds = 8
        config.out_of_range_timeout_seconds = 20
        config.heartbeat_interval_seconds = 5
        config.save()

        device = Device.objects.create(
            device_id='phase-1-laptop',
            name='My Laptop',
            device_type='ble_receiver',
            location='Development Laptop',
        )
        self.receiver = BLEReceiver.objects.create(
            device=device,
            platform='windows',
            status='online',
            last_online=timezone.now(),
        )

    def create_beacon(self, goat_id, minor):
        goat = Goat.objects.create(
            goat_id=goat_id,
            name=f'Goat {goat_id}',
            gender='female',
        )
        return BLEBeacon.objects.create(
            goat=goat,
            device_name=f'CP101-{minor:04d}',
            mac_address=f'48:87:2D:9E:3E:{minor:02X}',
            uuid=self.UUID,
            major=1,
            minor=minor,
        )

    def create_state(self, beacon, last_seen, proximity='near'):
        return BLETrackingState.objects.create(
            beacon=beacon,
            receiver=self.receiver,
            current_rssi=-58,
            smoothed_rssi=-57,
            proximity=proximity,
            status='detected',
            last_seen=last_seen,
            sample_count=3,
        )

    def test_statuses_age_through_detected_lost_and_out_of_range(self):
        now = timezone.now()
        detected = self.create_state(
            self.create_beacon('G001', 1),
            now - timedelta(seconds=3),
            'near',
        )
        possibly_lost = self.create_state(
            self.create_beacon('G002', 2),
            now - timedelta(seconds=10),
            'medium',
        )
        out_of_range = self.create_state(
            self.create_beacon('G003', 3),
            now - timedelta(seconds=21),
            'far',
        )

        refresh_tracking_statuses(now)

        detected.refresh_from_db()
        possibly_lost.refresh_from_db()
        out_of_range.refresh_from_db()
        self.assertEqual(detected.status, 'detected')
        self.assertEqual(possibly_lost.status, 'possibly_lost')
        self.assertEqual(possibly_lost.proximity, 'medium')
        self.assertEqual(out_of_range.status, 'out_of_range')
        self.assertEqual(out_of_range.proximity, 'out_of_range')
        self.assertEqual(out_of_range.current_rssi, -58)

    def test_exact_timeout_boundaries_do_not_expire_early(self):
        now = timezone.now()
        detected_boundary = self.create_state(
            self.create_beacon('G010', 10),
            now - timedelta(seconds=8),
        )
        lost_boundary = self.create_state(
            self.create_beacon('G011', 11),
            now - timedelta(seconds=20),
        )

        refresh_tracking_statuses(now)

        detected_boundary.refresh_from_db()
        lost_boundary.refresh_from_db()
        self.assertEqual(detected_boundary.status, 'detected')
        self.assertEqual(lost_boundary.status, 'possibly_lost')

    def test_receiver_is_offline_after_three_missed_heartbeats(self):
        now = timezone.now()
        self.receiver.last_online = now - timedelta(seconds=16)
        self.receiver.save(update_fields=['last_online', 'updated_at'])

        refresh_tracking_statuses(now)

        self.receiver.refresh_from_db()
        self.assertEqual(self.receiver.status, 'offline')

    def test_snapshot_includes_never_seen_trackers_and_honest_summary(self):
        now = timezone.now()
        self.create_state(
            self.create_beacon('G021', 21),
            now - timedelta(seconds=2),
            'very_near',
        )
        self.create_state(
            self.create_beacon('G022', 22),
            now - timedelta(seconds=10),
            'medium',
        )
        self.create_state(
            self.create_beacon('G023', 23),
            now - timedelta(seconds=25),
            'far',
        )
        self.create_beacon('G024', 24)

        snapshot = build_tracking_snapshot(now)

        self.assertEqual(snapshot['summary']['tracked_goats'], 4)
        self.assertEqual(snapshot['summary']['detected'], 1)
        self.assertEqual(snapshot['summary']['possibly_lost'], 1)
        self.assertEqual(snapshot['summary']['out_of_range'], 2)
        self.assertEqual(snapshot['summary']['very_near'], 1)
        never_seen = next(
            row for row in snapshot['goats']
            if row['goat']['goat_id'] == 'G024'
        )
        self.assertEqual(never_seen['status'], 'out_of_range')
        self.assertIsNone(never_seen['last_seen'])
        self.assertIsNone(never_seen['current_rssi'])


    def test_snapshot_can_be_scoped_to_smart_farm_goats(self):
        self.create_beacon('FARM-001', 31)
        community = self.create_beacon('COMMUNITY-001', 32)
        community.goat.record_source = Goat.COMMUNITY
        community.goat.save(update_fields=['record_source'])

        snapshot = build_tracking_snapshot(record_source=Goat.SMART_FARM)

        self.assertEqual(snapshot['summary']['tracked_goats'], 1)
        self.assertEqual(snapshot['goats'][0]['goat']['goat_id'], 'FARM-001')


class BLETrackingPageAndApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='tracking-admin',
            password='test-password',
        )
        farm_group, _ = Group.objects.get_or_create(name=FARM_OPERATOR_GROUP_NAME)
        self.user.groups.add(farm_group)
        self.goat = Goat.objects.create(
            goat_id='298439',
            name='jericson',
            gender='male',
        )
        self.beacon = BLEBeacon.objects.create(
            goat=self.goat,
            device_name='CP101-3E95',
            mac_address='48:87:2D:9E:3E:95',
            uuid='E2C56DB5-DFFB-48D2-B060-D0F5A71096E0',
            major=1,
            minor=1,
        )

    def test_page_and_snapshot_require_login(self):
        page = self.client.get(reverse('iot:ble_tracking_dashboard'))
        find_page = self.client.get(
            reverse('iot:ble_find_goat', args=['298439'])
        )
        api = APIClient().get(reverse('iot:ble_tracking_snapshot'))

        self.assertEqual(page.status_code, 302)
        self.assertIn('/accounts/login/', page.url)
        self.assertEqual(find_page.status_code, 302)
        self.assertIn('/accounts/login/', find_page.url)
        self.assertIn(api.status_code, {401, 403})

    def test_tracking_page_renders_native_controls_and_accuracy_notice(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('iot:ble_tracking_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Live Goat Tracking')
        self.assertContains(response, 'Goat Tracking Radar')
        self.assertContains(response, 'Proximity only — not exact location')
        self.assertContains(
            response,
            'Marker angle is decorative, not a physical direction.',
        )
        self.assertContains(response, 'Out of Range (list only)')
        self.assertContains(response, 'Possibly Lost')
        self.assertContains(response, 'Out of Range')
        self.assertContains(response, reverse('iot:ble_tracking_snapshot'))

    def test_find_goat_mode_is_focused_and_linked_from_profile(self):
        self.client.force_login(self.user)

        find_url = reverse('iot:ble_find_goat', args=['298439'])
        response = self.client.get(find_url)
        profile = self.client.get(
            reverse('iot:goat_detail_enhanced', args=['298439'])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Find Goat 298439')
        self.assertContains(response, 'Searching for jericson')
        self.assertContains(response, 'data-focus-goat-id="298439"')
        self.assertContains(response, 'Signal strength')
        self.assertContains(response, 'not direction or exact distance')
        self.assertEqual(profile.status_code, 200)
        self.assertContains(profile, find_url)
        self.assertContains(profile, 'Find Goat')

    def test_find_goat_rejects_untracked_or_disabled_goat(self):
        self.client.force_login(self.user)
        Goat.objects.create(
            goat_id='NO-TRACKER',
            name='No Tracker',
            gender='female',
        )

        untracked = self.client.get(
            reverse('iot:ble_find_goat', args=['NO-TRACKER'])
        )
        self.beacon.enabled = False
        self.beacon.save(update_fields=['enabled', 'updated_at'])
        disabled = self.client.get(
            reverse('iot:ble_find_goat', args=['298439'])
        )

        self.assertEqual(untracked.status_code, 404)
        self.assertEqual(disabled.status_code, 404)

    def test_authenticated_snapshot_returns_goat_and_summary(self):
        client = APIClient()
        client.force_authenticate(user=self.user)

        response = client.get(reverse('iot:ble_tracking_snapshot'))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['summary']['tracked_goats'], 1)
        self.assertEqual(response.data['summary']['out_of_range'], 1)
        self.assertEqual(response.data['goats'][0]['goat']['goat_id'], '298439')
        self.assertEqual(
            response.data['goats'][0]['goat']['detail_url'],
            reverse('iot:goat_detail_enhanced', args=['298439']),
        )

    @patch(
        'iot.views.get_farm_weather',
        return_value={'available': False},
    )
    def test_admin_dashboard_includes_live_ble_summary(self, _weather):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        self.client.force_login(self.user)

        response = self.client.get(reverse('iot:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BLE Goat Tracking')
        self.assertContains(response, 'Currently Detected')
        self.assertContains(response, 'Out of Range')
        self.assertContains(response, 'Open radar')
        self.assertContains(response, reverse('iot:ble_tracking_dashboard'))
        self.assertContains(response, reverse('iot:ble_tracking_snapshot'))
        self.assertEqual(
            response.context['ble_tracking_summary']['tracked_goats'],
            1,
        )
        self.assertEqual(
            response.context['ble_tracking_summary']['out_of_range'],
            1,
        )
