import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ble_scanner_service.cli import (
    backend_config_from_args,
    build_parser,
    load_environment,
)


class ScannerEnvironmentTests(unittest.TestCase):
    def test_explicit_receiver_file_ignores_stale_laptop_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / 'receiver.env'
            env_file.write_text(
                'BLE_BACKEND_URL=https://farm.example/iot/api/ble\n'
                'BLE_RECEIVER_ID=pi-receiver\n'
                'BLE_RECEIVER_KEY=pi-secret\n'
            )
            with mock.patch.dict(os.environ, {
                'BLE_SCANNER_ENV_FILE': str(env_file),
                'BLE_BACKEND_URL': 'http://127.0.0.1:8000/iot/api/ble',
                'BLE_RECEIVER_ID': 'old-laptop',
                'BLE_RECEIVER_KEY': 'old-secret',
            }, clear=True):
                load_environment()
                config = backend_config_from_args(build_parser().parse_args([]))

            self.assertEqual(config.base_url, 'https://farm.example/iot/api/ble')
            self.assertEqual(config.receiver_id, 'pi-receiver')
            self.assertEqual(config.receiver_key, 'pi-secret')

    def test_missing_explicit_file_does_not_fall_back_to_laptop(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {
                'BLE_SCANNER_ENV_FILE': str(Path(directory) / 'missing.env'),
            }, clear=True):
                with self.assertRaisesRegex(ValueError, 'does not exist'):
                    load_environment()

    def test_default_keeps_local_development_settings(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch('ble_scanner_service.cli.load_dotenv') as load:
                load_environment()
        self.assertEqual(load.call_args_list, [
            mock.call(),
            mock.call('ble_scanner.local.env', override=True),
        ])
