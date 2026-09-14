from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from marketplace.auth import FARM_OWNER_GROUP_NAME

from .models import (
    BLEBeacon,
    BLEReceiver,
    BLETrackingSettings,
    BLETrackingState,
    Device,
    Goat,
    SensorReading,
)


@override_settings(IOT_DEVICE_API_KEY="test-device-key")
class IndoorEnvironmentSensorApiTests(TestCase):
    headers = {"HTTP_X_GOHMOTECH_DEVICE_KEY": "test-device-key"}

    def test_upload_requires_device_credentials(self):
        response = APIClient().post(
            "/iot/api/sensor-readings/",
            {"device_id": "unauthorized_sensor", "temperature": 29.4},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Device.objects.filter(device_id="unauthorized_sensor").exists())

    def test_upload_rejects_invalid_device_credentials(self):
        response = APIClient().post(
            "/iot/api/sensor-readings/",
            {"device_id": "unauthorized_sensor", "temperature": 29.4},
            format="json",
            HTTP_X_GOHMOTECH_DEVICE_KEY="wrong-key",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Device.objects.filter(device_id="unauthorized_sensor").exists())

    def test_esp32_can_upload_light_and_mq135_readings(self):
        response = APIClient().post(
            "/iot/api/sensor-readings/",
            {
                "device_id": "kamotech_esp32_001",
                "device_name": "GoHMoTech ESP32",
                "temperature": 29.4,
                "humidity": 71.2,
                "light_raw": 840,
                "light_level_percentage": 83.1,
                "air_quality_raw": 1120,
                "air_quality_voltage": 0.902,
                "air_quality_calibrated": False,
            },
            format="json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 201, response.data)
        reading = SensorReading.objects.get()
        self.assertEqual(reading.light_raw, 840)
        self.assertEqual(reading.air_quality_raw, 1120)
        self.assertFalse(reading.air_quality_calibrated)
        self.assertIsNone(reading.air_quality_ppm)

    def test_adc_and_percentage_ranges_are_validated(self):
        response = APIClient().post(
            "/iot/api/sensor-readings/",
            {
                "device_id": "invalid_sensor",
                "light_raw": 5000,
                "light_level_percentage": 101,
                "air_quality_raw": 5000,
            },
            format="json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("light_raw", response.data)
        self.assertIn("light_level_percentage", response.data)
        self.assertIn("air_quality_raw", response.data)


class BLEDatabaseFoundationTests(TestCase):
    IBEACON_UUID = 'E2C56DB5DFFB48D2B060D0F5A71096E0'
    CANONICAL_UUID = 'E2C56DB5-DFFB-48D2-B060-D0F5A71096E0'

    def setUp(self):
        self.goat = Goat.objects.create(
            goat_id='298439',
            name='jericson',
            gender='male',
        )
        self.other_goat = Goat.objects.create(
            goat_id='G002',
            name='Goat G002',
            gender='female',
        )
        device = Device.objects.create(
            device_id='ble-laptop-01',
            name='Phase 1 Laptop',
            device_type='ble_receiver',
            location='Development Laptop',
        )
        self.receiver = BLEReceiver.objects.create(
            device=device,
            platform='windows',
            device_name='TEST-LAPTOP',
        )

    def create_beacon(self, **overrides):
        values = {
            'goat': self.goat,
            'device_name': 'CP101-3E95',
            'mac_address': '48-87-2d-9e-3e-95',
            'uuid': self.IBEACON_UUID,
            'major': 1,
            'minor': 1,
            'calibrated_rssi': -57,
            'advertising_interval_ms': 450,
            'tx_power_dbm': '2.50',
        }
        values.update(overrides)
        return BLEBeacon.objects.create(**values)

    def test_beacon_identity_is_normalized_on_save(self):
        beacon = self.create_beacon()

        self.assertEqual(beacon.mac_address, '48:87:2D:9E:3E:95')
        self.assertEqual(beacon.uuid, self.CANONICAL_UUID)
        self.assertEqual(beacon.goat, self.goat)
        self.assertIsNone(self.goat.last_seen)

    def test_same_mac_cannot_be_assigned_to_another_goat(self):
        self.create_beacon()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_beacon(
                    goat=self.other_goat,
                    uuid='11111111111111111111111111111111',
                    major=2,
                    minor=2,
                )

    def test_same_ibeacon_identity_cannot_be_assigned_twice(self):
        self.create_beacon()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_beacon(
                    goat=self.other_goat,
                    mac_address='AA:BB:CC:DD:EE:FF',
                )

    def test_goat_cannot_have_multiple_beacons(self):
        self.create_beacon()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_beacon(
                    mac_address='AA:BB:CC:DD:EE:FF',
                    uuid='11111111111111111111111111111111',
                    major=2,
                    minor=2,
                )

    def test_unassigned_beacons_can_have_missing_mac_addresses(self):
        first = self.create_beacon(goat=None, mac_address=None)
        second = self.create_beacon(
            goat=None,
            mac_address='',
            uuid='11111111111111111111111111111111',
            major=2,
            minor=2,
        )

        self.assertIsNone(first.mac_address)
        self.assertIsNone(second.mac_address)

    def test_only_one_current_state_exists_per_receiver_and_beacon(self):
        beacon = self.create_beacon()
        BLETrackingState.objects.create(
            beacon=beacon,
            receiver=self.receiver,
            current_rssi=-52,
            smoothed_rssi=-54.0,
            proximity='near',
            status='detected',
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BLETrackingState.objects.create(
                    beacon=beacon,
                    receiver=self.receiver,
                )

    def test_tracking_settings_are_singleton_and_validate_ordering(self):
        settings = BLETrackingSettings.get_config()
        same_settings = BLETrackingSettings.get_config()

        self.assertEqual(settings.pk, same_settings.pk)
        self.assertEqual(BLETrackingSettings.objects.count(), 1)

        settings.very_near_min_rssi = -70
        settings.near_min_rssi = -60
        with self.assertRaises(ValidationError):
            settings.full_clean()

        settings.refresh_from_db()
        settings.possibly_lost_timeout_seconds = 20
        settings.out_of_range_timeout_seconds = 20
        with self.assertRaises(ValidationError):
            settings.full_clean()


class BLEGoatInventoryIntegrationTests(TestCase):
    IBEACON_UUID = 'E2C56DB5DFFB48D2B060D0F5A71096E0'

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='inventory-admin',
            password='test-password',
        )
        farm_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        self.user.groups.add(farm_group)
        self.client.force_login(self.user)

    def goat_payload(self, goat_id='NEW001'):
        return {
            'goat_id': goat_id,
            'name': 'Inventory Test Goat',
            'tag_number': '',
            'breed': 'native',
            'gender': 'male',
            'date_of_birth': '',
            'weight_kg': '',
            'color_markings': '',
            'health_status': 'healthy',
            'health_notes': '',
            'vaccination_status': 'unknown',
            'vaccine_name': '',
            'vaccination_date': '',
            'next_due_date': '',
            'notes': '',
            'captured_photo': '',
        }

    def beacon_payload(self):
        return {
            'ble-enabled': 'on',
            'ble-device_name': 'CP101-3E95',
            'ble-mac_address': '48:87:2D:9E:3E:95',
            'ble-uuid': self.IBEACON_UUID,
            'ble-major': '1',
            'ble-minor': '1',
            'ble-calibrated_rssi': '-57',
            'ble-advertising_interval_ms': '450',
            'ble-tx_power_dbm': '2.50',
            'ble-battery_level': '100',
        }

    def test_add_goat_does_not_require_a_beacon(self):
        response = self.client.post(reverse('iot:add_goat'), self.goat_payload())

        self.assertEqual(response.status_code, 302)
        goat = Goat.objects.get(goat_id='NEW001')
        self.assertFalse(BLEBeacon.objects.filter(goat=goat).exists())

    def test_add_goat_can_assign_a_beacon(self):
        payload = self.goat_payload()
        payload.update(self.beacon_payload())

        response = self.client.post(reverse('iot:add_goat'), payload)

        self.assertEqual(response.status_code, 302)
        beacon = BLEBeacon.objects.get(goat__goat_id='NEW001')
        self.assertTrue(beacon.enabled)
        self.assertEqual(beacon.device_name, 'CP101-3E95')
        self.assertEqual(beacon.mac_address, '48:87:2D:9E:3E:95')
        self.assertEqual(beacon.major, 1)
        self.assertEqual(beacon.minor, 1)

    def test_duplicate_beacon_prevents_new_goat_creation(self):
        existing_goat = Goat.objects.create(
            goat_id='EXISTING', name='Existing Goat', gender='female'
        )
        BLEBeacon.objects.create(
            goat=existing_goat,
            device_name='CP101-3E95',
            mac_address='48:87:2D:9E:3E:95',
            uuid=self.IBEACON_UUID,
            major=1,
            minor=1,
            calibrated_rssi=-57,
        )
        payload = self.goat_payload(goat_id='DUPLICATE')
        payload.update(self.beacon_payload())

        response = self.client.post(reverse('iot:add_goat'), payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertFalse(Goat.objects.filter(goat_id='DUPLICATE').exists())

    def test_manage_goat_can_disable_assigned_tracking(self):
        goat = Goat.objects.create(
            goat_id='MANAGE001', name='Managed Goat', gender='male'
        )
        beacon = BLEBeacon.objects.create(
            goat=goat,
            device_name='CP101-3E95',
            mac_address='48:87:2D:9E:3E:95',
            uuid=self.IBEACON_UUID,
            major=1,
            minor=1,
            calibrated_rssi=-57,
        )
        payload = self.goat_payload(goat_id=goat.goat_id)
        payload.update(self.beacon_payload())
        payload.pop('ble-enabled')

        response = self.client.post(
            reverse('iot:goat_detail_enhanced', args=[goat.goat_id]),
            payload,
        )

        self.assertEqual(response.status_code, 302)
        beacon.refresh_from_db()
        self.assertFalse(beacon.enabled)

    def test_inventory_and_manage_pages_render_ble_assignment(self):
        goat = Goat.objects.create(
            goat_id='VISIBLE001', name='Visible Goat', gender='female'
        )
        BLEBeacon.objects.create(
            goat=goat,
            device_name='CP101-3E95',
            mac_address='48:87:2D:9E:3E:95',
            uuid=self.IBEACON_UUID,
            major=1,
            minor=1,
            calibrated_rssi=-57,
        )

        inventory_response = self.client.get(reverse('iot:goat_inventory'))
        manage_response = self.client.get(
            reverse('iot:goat_detail_enhanced', args=[goat.goat_id])
        )

        self.assertEqual(inventory_response.status_code, 200)
        self.assertContains(inventory_response, 'CP101-3E95')
        self.assertEqual(manage_response.status_code, 200)
        self.assertContains(manage_response, 'Current Tracking State')
        self.assertContains(manage_response, 'No BLE detections have been received yet')
