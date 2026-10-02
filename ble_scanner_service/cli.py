"""Command-line entry point for laptop scanner development and diagnostics."""

import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from .backend import BackendConfig, BLEBackendReporter, SCANNER_VERSION
from .config import GOHMOTECH_IBEACON_UUID, ScannerConfig
from .scanner import PortableBLEScanner


def load_environment():
    """Keep an explicitly configured receiver separate from laptop settings."""
    env_file = os.getenv('BLE_SCANNER_ENV_FILE')
    if env_file:
        if not Path(env_file).is_file():
            raise ValueError(f'BLE scanner environment file does not exist: {env_file}')
        load_dotenv(env_file, override=True)
    else:
        load_dotenv()
        load_dotenv('ble_scanner.local.env', override=True)


def _env_number(name, default, converter=float):
    value = os.getenv(name)
    return default if value in (None, '') else converter(value)


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            'Continuously scan GoHMoTech iBeacon advertisements without pairing '
            'or connecting to the beacon.'
        )
    )
    parser.add_argument(
        '--target-uuid',
        default=os.getenv('BLE_TARGET_UUID', GOHMOTECH_IBEACON_UUID),
        help='GoHMoTech iBeacon UUID to accept.',
    )
    parser.add_argument(
        '--target-mac', default=os.getenv('BLE_TARGET_MAC'),
        help='Optional additional MAC/address filter.',
    )
    parser.add_argument(
        '--target-name', default=os.getenv('BLE_TARGET_NAME'),
        help='Optional additional exact device-name filter.',
    )
    parser.add_argument(
        '--scan-mode', choices=['passive', 'active'],
        default=os.getenv('BLE_SCAN_MODE', 'active'),
        help=(
            'Bleak discovery mode. Windows requires active; it remains '
            'connectionless and does not pair or connect.'
        ),
    )
    parser.add_argument(
        '--smoothing', choices=['median', 'moving_average'],
        default=os.getenv('BLE_SMOOTHING_METHOD', 'median'),
    )
    parser.add_argument(
        '--window', type=int,
        default=_env_number('BLE_SMOOTHING_WINDOW', 5, int),
        help='RSSI smoothing window size (3-50).',
    )
    parser.add_argument(
        '--report-interval', type=float,
        default=_env_number('BLE_REPORT_INTERVAL_SECONDS', 1.0),
        help='Minimum seconds between summarized output lines per beacon.',
    )
    parser.add_argument(
        '--restart-interval', type=float,
        default=_env_number('BLE_RESTART_INTERVAL_SECONDS', 300.0),
        help='Periodically restart the OS watcher to recover from silent failures.',
    )
    parser.add_argument(
        '--duration', type=float, default=None,
        help='Stop after this many seconds; omit for continuous scanning.',
    )
    parser.add_argument(
        '--raw', action='store_true',
        help='Print raw manufacturer advertisements for matching candidates.',
    )
    parser.add_argument(
        '--show-all', action='store_true',
        help='With raw diagnostics, show all nearby BLE advertisements.',
    )
    parser.add_argument(
        '--backend-url',
        default=os.getenv('BLE_BACKEND_URL'),
        help='BLE API base URL, for example http://127.0.0.1:8000/iot/api/ble.',
    )
    parser.add_argument(
        '--backend-host',
        default=os.getenv('BLE_BACKEND_HOST'),
        help='HTTP Host header when using a loopback reverse proxy on this Pi.',
    )
    parser.add_argument(
        '--receiver-id',
        default=os.getenv('BLE_RECEIVER_ID'),
        help='Provisioned receiver identifier. The key is read from BLE_RECEIVER_KEY.',
    )
    parser.add_argument(
        '--backend-timeout',
        type=float,
        default=_env_number('BLE_BACKEND_TIMEOUT_SECONDS', 5.0),
    )
    parser.add_argument(
        '--backend-queue-size',
        type=int,
        default=_env_number('BLE_BACKEND_QUEUE_SIZE', 100, int),
    )
    parser.add_argument(
        '--no-backend',
        action='store_true',
        help='Scan locally without sending heartbeats or observations.',
    )
    parser.add_argument('--debug', action='store_true')
    parser.add_argument(
        '--version',
        action='version',
        version=f'GoHMoTech BLE scanner {SCANNER_VERSION}',
    )
    return parser


def config_from_args(args):
    return ScannerConfig(
        target_uuid=args.target_uuid,
        target_mac=args.target_mac,
        target_name=args.target_name,
        scan_mode=args.scan_mode,
        smoothing_method=args.smoothing,
        smoothing_window=args.window,
        report_interval_seconds=args.report_interval,
        restart_interval_seconds=args.restart_interval,
        duration_seconds=args.duration,
        raw_output=args.raw or args.show_all,
        show_all_devices=args.show_all,
    )


def backend_config_from_args(args):
    if args.no_backend:
        return None
    receiver_key = os.getenv('BLE_RECEIVER_KEY')
    supplied = any((args.backend_url, args.receiver_id, receiver_key))
    if not supplied:
        return None
    if not all((args.backend_url, args.receiver_id, receiver_key)):
        raise ValueError(
            'Backend reporting requires BLE_BACKEND_URL, BLE_RECEIVER_ID, '
            'and BLE_RECEIVER_KEY.'
        )
    return BackendConfig(
        base_url=args.backend_url,
        receiver_id=args.receiver_id,
        receiver_key=receiver_key,
        request_timeout_seconds=args.backend_timeout,
        queue_size=args.backend_queue_size,
        host_header=args.backend_host,
    )


async def run_scanner(args):
    scanner_config = config_from_args(args)
    backend_config = backend_config_from_args(args)
    reporter = BLEBackendReporter(backend_config) if backend_config else None
    scanner = PortableBLEScanner(
        scanner_config,
        event_handler=reporter.enqueue if reporter else None,
    )

    if reporter:
        reporter.assignment_handler = scanner.register_known_beacons
        await reporter.start()
    try:
        await scanner.run()
    finally:
        if reporter:
            await reporter.stop()


def main(argv=None):
    try:
        load_environment()
        args = build_parser().parse_args(argv)
        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format='%(asctime)s %(levelname)s %(message)s',
        )
        asyncio.run(run_scanner(args))
    except KeyboardInterrupt:
        logging.getLogger(__name__).info('Stopped by user.')
    except (RuntimeError, ValueError) as exc:
        logging.getLogger(__name__).error('%s', exc)
        return 2
    return 0
