import asyncio
import unittest
from unittest import mock

from ble_scanner_service.backend import BackendConfig, BLEBackendReporter
from ble_scanner_service.config import ScannerConfig
from ble_scanner_service.scanner import PortableBLEScanner


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = ''

    def json(self):
        return self._body


class BackendConfigTests(unittest.TestCase):
    def test_requires_absolute_http_url_and_credentials(self):
        with self.assertRaises(ValueError):
            BackendConfig('localhost:8000', 'laptop', 'secret')
        with self.assertRaises(ValueError):
            BackendConfig('http://localhost:8000/iot/api/ble', '', 'secret')
        with self.assertRaises(ValueError):
            BackendConfig('http://localhost:8000/iot/api/ble', 'laptop', '')

    def test_normalizes_trailing_slash(self):
        config = BackendConfig(
            'http://127.0.0.1:8000/iot/api/ble/',
            'phase-1-laptop',
            'secret',
        )
        self.assertEqual(
            config.base_url,
            'http://127.0.0.1:8000/iot/api/ble',
        )

    def test_host_override_is_limited_to_loopback_and_rejects_newlines(self):
        with self.assertRaisesRegex(ValueError, 'loopback'):
            BackendConfig(
                'https://farm.example/iot/api/ble', 'pi', 'secret',
                host_header='farm.example',
            )
        with self.assertRaisesRegex(ValueError, 'whitespace'):
            BackendConfig(
                'http://127.0.0.1:8080/iot/api/ble', 'pi', 'secret',
                host_header='farm.example\r\nOther: value',
            )


class BackendReporterTests(unittest.IsolatedAsyncioTestCase):
    async def test_loopback_proxy_receives_host_and_receiver_auth(self):
        reporter = BLEBackendReporter(BackendConfig(
            'http://127.0.0.1:8080/iot/api/ble', 'pi', 'secret',
            host_header='farm.example',
        ))
        with mock.patch('ble_scanner_service.backend.requests.post') as post:
            post.return_value = FakeResponse({'accepted': True})
            await reporter._post_json('observations/', {'rssi': -50})
        self.assertEqual(
            post.call_args.args[0],
            'http://127.0.0.1:8080/iot/api/ble/observations/',
        )
        headers = post.call_args.kwargs['headers']
        self.assertEqual(headers['Host'], 'farm.example')
        self.assertEqual(headers['X-Receiver-ID'], 'pi')
        self.assertEqual(headers['Authorization'], 'Bearer secret')

    async def test_heartbeat_assignments_and_observations_use_receiver_auth(self):
        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith('/heartbeat/'):
                return FakeResponse({
                    'tracking_config': {'heartbeat_interval_seconds': 60},
                    'beacons': [{
                        'mac_address': '48:87:2D:9E:3E:95',
                        'uuid': 'E2C56DB5-DFFB-48D2-B060-D0F5A71096E0',
                        'major': 1,
                        'minor': 1,
                    }],
                })
            return FakeResponse({
                'accepted': True,
                'history_saved': True,
                'goat': {'goat_id': '298439'},
                'state': {'proximity': 'near', 'status': 'detected'},
            })

        assignments = []
        config = BackendConfig(
            'http://127.0.0.1:8000/iot/api/ble',
            'phase-1-laptop',
            'receiver-secret',
        )
        reporter = BLEBackendReporter(config, assignments.extend)

        with mock.patch(
            'ble_scanner_service.backend.requests.post',
            side_effect=fake_post,
        ):
            await reporter.start()
            reporter.enqueue({
                'protocol': 'eddystone_uid',
                'address': '48:87:2D:9E:3E:95',
                'uuid': None,
                'major': None,
                'minor': None,
                'rssi': -58,
                'smoothed_rssi': -57.0,
                'seen_at': '2026-08-18T00:00:00+00:00',
            })
            await asyncio.wait_for(reporter._queue.join(), timeout=2)
            await reporter.stop()

        self.assertEqual(len(assignments), 1)
        self.assertEqual(len(calls), 2)
        for _url, kwargs in calls:
            self.assertEqual(
                kwargs['headers']['X-Receiver-ID'],
                'phase-1-laptop',
            )
            self.assertEqual(
                kwargs['headers']['Authorization'],
                'Bearer receiver-secret',
            )
        self.assertTrue(calls[0][0].endswith('/heartbeat/'))
        self.assertTrue(calls[1][0].endswith('/observations/'))

    async def test_bounded_queue_discards_oldest_observation(self):
        reporter = BLEBackendReporter(
            BackendConfig(
                'http://127.0.0.1:8000/iot/api/ble',
                'phase-1-laptop',
                'secret',
                queue_size=1,
            )
        )
        reporter.enqueue({'rssi': -90})
        reporter.enqueue({'rssi': -50})

        self.assertEqual(reporter._queue.qsize(), 1)
        self.assertEqual((await reporter._queue.get())['rssi'], -50)
        reporter._queue.task_done()


class BackendAssignmentsScannerTests(unittest.TestCase):
    def test_backend_assignment_enables_mac_fallback_without_cli_filter(self):
        scanner = PortableBLEScanner(ScannerConfig())
        scanner.register_known_beacons([{
            'mac_address': '48-87-2d-9e-3e-95',
            'uuid': 'E2C56DB5-DFFB-48D2-B060-D0F5A71096E0',
            'major': 1,
            'minor': 1,
        }])

        self.assertTrue(
            scanner._matches_target('48:87:2D:9E:3E:95', None, None)
        )
        self.assertFalse(
            scanner._matches_target('AA:BB:CC:DD:EE:FF', None, None)
        )


if __name__ == '__main__':
    unittest.main()
