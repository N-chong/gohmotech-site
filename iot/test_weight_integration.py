import json
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from marketplace.auth import FARM_OWNER_GROUP_NAME

from .models import Goat, GoatWeightMeasurement


TEST_CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'goat-weight-tests',
    }
}


@override_settings(CACHES=TEST_CACHES, IOT_DEVICE_API_KEY='test-scale-key')
class GoatWeightIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username='weight-farmer',
            password='test-password',
        )
        farm_group, _ = Group.objects.get_or_create(name=FARM_OWNER_GROUP_NAME)
        self.user.groups.add(farm_group)
        self.client.force_login(self.user)
        self.goat = Goat.objects.create(
            goat_id='GOAT-001',
            name='Daisy',
            gender='female',
        )

    def post_json(self, url, payload):
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_GOHMOTECH_DEVICE_KEY='test-scale-key',
        )

    def test_scale_ingest_rejects_browser_session_without_device_key(self):
        response = self.client.post(
            reverse('iot:scale_reading_ingest'),
            data=json.dumps(self.scale_payload()),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(cache.get('iot:scale:latest:kamotech_scale_esp32_001'))

    def scale_payload(self, weight=24.65, stable=True, detected=True, ready=True):
        return {
            'device_id': 'kamotech_scale_esp32_001',
            'hx711_ready': ready,
            'valid': ready,
            'weight_detected': detected,
            'stable': stable,
            'weight_kg': weight,
            'variation_kg': 0.08,
        }

    def test_live_snapshot_does_not_create_weight_history(self):
        response = self.post_json(
            reverse('iot:scale_reading_ingest'),
            self.scale_payload(),
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(GoatWeightMeasurement.objects.count(), 0)
        self.goat.refresh_from_db()
        self.assertIsNone(self.goat.weight_kg)

        live = self.client.get(reverse('iot:goat_weight_live', args=[self.goat.goat_id]))
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json()['selected_goat']['goat_id'], self.goat.goat_id)
        self.assertEqual(live.json()['weight_kg'], 24.65)
        self.assertTrue(live.json()['stable'])

    def test_stable_load_cell_weight_requires_confirmation_then_saves(self):
        self.post_json(reverse('iot:scale_reading_ingest'), self.scale_payload())

        response = self.post_json(
            reverse('iot:save_goat_weight', args=[self.goat.goat_id]),
            {
                'source': 'load_cell',
                'request_id': str(uuid.uuid4()),
                'weight_kg': 99.99,
            },
        )

        self.assertEqual(response.status_code, 201)
        measurement = GoatWeightMeasurement.objects.get()
        self.assertEqual(measurement.goat, self.goat)
        self.assertEqual(measurement.weight_kg, Decimal('24.65'))
        self.assertEqual(measurement.source, GoatWeightMeasurement.SOURCE_LOAD_CELL)
        self.assertEqual(measurement.device_id, 'kamotech_scale_esp32_001')
        self.goat.refresh_from_db()
        self.assertEqual(self.goat.weight_kg, 24.65)

    def test_unstable_load_cell_weight_is_rejected(self):
        self.post_json(
            reverse('iot:scale_reading_ingest'),
            self.scale_payload(stable=False),
        )

        response = self.post_json(
            reverse('iot:save_goat_weight', args=[self.goat.goat_id]),
            {'source': 'load_cell', 'request_id': str(uuid.uuid4())},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn('stable', response.json()['error'].lower())
        self.assertFalse(GoatWeightMeasurement.objects.exists())

    def test_manual_weights_append_history_and_update_current_weight(self):
        save_url = reverse('iot:save_goat_weight', args=[self.goat.goat_id])
        first = self.post_json(
            save_url,
            {'source': 'manual', 'weight_kg': '23.80', 'request_id': str(uuid.uuid4())},
        )
        second = self.post_json(
            save_url,
            {'source': 'manual', 'weight_kg': '24.10', 'request_id': str(uuid.uuid4())},
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(self.goat.weight_measurements.count(), 2)
        self.goat.refresh_from_db()
        self.assertEqual(self.goat.weight_kg, 24.10)

    def test_manual_weight_validation_rejects_invalid_values(self):
        save_url = reverse('iot:save_goat_weight', args=[self.goat.goat_id])
        for value in ('not-a-number', '0', '-2', '301'):
            response = self.post_json(
                save_url,
                {'source': 'manual', 'weight_kg': value, 'request_id': str(uuid.uuid4())},
            )
            self.assertEqual(response.status_code, 400, value)
        self.assertFalse(GoatWeightMeasurement.objects.exists())

    def test_duplicate_save_request_is_idempotent(self):
        request_id = str(uuid.uuid4())
        payload = {'source': 'manual', 'weight_kg': '22.90', 'request_id': request_id}
        save_url = reverse('iot:save_goat_weight', args=[self.goat.goat_id])

        first = self.post_json(save_url, payload)
        second = self.post_json(save_url, payload)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()['duplicate'])
        self.assertEqual(GoatWeightMeasurement.objects.count(), 1)

    def test_weight_card_and_history_render_on_selected_goat_page(self):
        GoatWeightMeasurement.objects.create(
            goat=self.goat,
            weight_kg=Decimal('23.80'),
            source=GoatWeightMeasurement.SOURCE_MANUAL,
            recorded_by=self.user,
        )
        self.goat.weight_kg = 23.80
        self.goat.save(update_fields=['weight_kg'])

        response = self.client.get(
            reverse('iot:goat_detail_enhanced', args=[self.goat.goat_id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Weight Monitoring')
        self.assertContains(response, 'Automatic / Load Cell')
        self.assertContains(response, 'Manual Entry')
        self.assertContains(response, '23.80 kg')
        self.assertContains(response, 'Weight History')

    def test_live_and_save_routes_require_a_selected_existing_goat(self):
        missing_live = self.client.get(reverse('iot:goat_weight_live', args=['MISSING']))
        missing_save = self.post_json(
            reverse('iot:save_goat_weight', args=['MISSING']),
            {'source': 'manual', 'weight_kg': '20', 'request_id': str(uuid.uuid4())},
        )

        self.assertEqual(missing_live.status_code, 404)
        self.assertEqual(missing_save.status_code, 404)
