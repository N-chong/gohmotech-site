"""Continuous, connectionless BLE scanner with portable recovery behavior."""

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
import time

from .config import normalize_mac
from .ibeacon import (
    identify_advertisement_protocol,
    manufacturer_data_hex,
    parse_ibeacon_manufacturer_data,
    service_data_hex,
)
from .smoothing import RSSISmoother

try:
    from bleak import BleakScanner
except ImportError:  # Friendly CLI error before dependencies are installed.
    BleakScanner = None


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BeaconReading:
    protocol: str
    address: str | None
    device_name: str | None
    uuid: str | None
    major: int | None
    minor: int | None
    rssi: int
    smoothed_rssi: float
    measured_power: int | None
    advertised_tx_power: int | None
    service_data: dict
    sample_count: int
    seen_at: str

    @property
    def identity(self):
        if self.uuid is not None:
            return self.uuid, self.major, self.minor
        return 'mac', self.address

    def to_dict(self):
        return asdict(self)


class PortableBLEScanner:
    """Scan iBeacon advertisements without pairing, bonding, or connecting."""

    def __init__(self, config, event_handler=None):
        self.config = config
        self.event_handler = event_handler
        self._smoothers = {}
        self._last_reported_at = {}
        self._known_macs = set()
        self._known_ibeacon_identities = set()
        self._stop_event = None

    def request_stop(self):
        if self._stop_event is not None:
            self._stop_event.set()

    def register_known_beacons(self, beacons):
        """Refresh assignments returned by the backend heartbeat."""
        known_macs = set()
        known_identities = set()
        for beacon in beacons or []:
            try:
                mac_address = normalize_mac(beacon.get('mac_address'))
            except ValueError:
                mac_address = None
            if mac_address:
                known_macs.add(mac_address)
            if all(beacon.get(field) is not None for field in ('uuid', 'major', 'minor')):
                known_identities.add(
                    (
                        str(beacon['uuid']).upper(),
                        int(beacon['major']),
                        int(beacon['minor']),
                    )
                )
        self._known_macs = known_macs
        self._known_ibeacon_identities = known_identities
        logger.debug(
            'Loaded %d known MAC(s) and %d iBeacon identity assignment(s).',
            len(known_macs),
            len(known_identities),
        )

    def _observed_mac(self, address):
        try:
            return normalize_mac(address)
        except ValueError:
            return str(address).upper() if address else None

    def _matches_target(self, address, device_name, ibeacon):
        observed_mac = self._observed_mac(address)
        if self.config.target_mac and observed_mac != self.config.target_mac:
            return False
        if self.config.target_name:
            if not device_name or device_name.casefold() != self.config.target_name.casefold():
                return False
        if ibeacon is not None:
            return ibeacon.uuid == self.config.target_uuid
        # A registered MAC may still be tracked when the hardware is currently
        # transmitting a non-iBeacon frame. Never invent UUID/major/minor data.
        return bool(
            (self.config.target_mac and observed_mac == self.config.target_mac)
            or observed_mac in self._known_macs
        )

    def _is_diagnostic_candidate(self, address, device_name, ibeacon):
        if self.config.show_all_devices:
            return True
        if ibeacon and ibeacon.uuid == self.config.target_uuid:
            return True
        if self.config.target_mac and self._observed_mac(address) == self.config.target_mac:
            return True
        if self._observed_mac(address) in self._known_macs:
            return True
        return bool(
            self.config.target_name
            and device_name
            and device_name.casefold() == self.config.target_name.casefold()
        )

    def _on_advertisement(self, device, advertisement_data):
        address = getattr(device, 'address', None)
        device_name = (
            getattr(advertisement_data, 'local_name', None)
            or getattr(device, 'name', None)
        )
        manufacturer_data = getattr(advertisement_data, 'manufacturer_data', {})
        service_data = getattr(advertisement_data, 'service_data', {})
        ibeacon = parse_ibeacon_manufacturer_data(manufacturer_data)
        protocol = identify_advertisement_protocol(ibeacon, service_data)
        rssi = int(getattr(advertisement_data, 'rssi'))

        if self.config.raw_output and self._is_diagnostic_candidate(
            address, device_name, ibeacon
        ):
            logger.info(
                'RAW address=%s name=%s rssi=%s tx_power=%s protocol=%s '
                'manufacturer_data=%s service_data=%s service_uuids=%s',
                address or 'unknown',
                device_name or 'unknown',
                rssi,
                getattr(advertisement_data, 'tx_power', None),
                protocol,
                manufacturer_data_hex(manufacturer_data),
                service_data_hex(service_data),
                ','.join(getattr(advertisement_data, 'service_uuids', []) or []) or 'none',
            )

        if not self._matches_target(address, device_name, ibeacon):
            return

        identity = (
            ibeacon.identity
            if ibeacon is not None
            else ('mac', self._observed_mac(address))
        )
        smoother = self._smoothers.setdefault(
            identity,
            RSSISmoother(
                window_size=self.config.smoothing_window,
                method=self.config.smoothing_method,
            ),
        )
        smoothed_rssi = smoother.add(rssi)

        now_monotonic = time.monotonic()
        last_report = self._last_reported_at.get(identity, 0.0)
        if now_monotonic - last_report < self.config.report_interval_seconds:
            return
        self._last_reported_at[identity] = now_monotonic

        reading = BeaconReading(
            protocol=protocol,
            address=address,
            device_name=device_name,
            uuid=ibeacon.uuid if ibeacon is not None else None,
            major=ibeacon.major if ibeacon is not None else None,
            minor=ibeacon.minor if ibeacon is not None else None,
            rssi=rssi,
            smoothed_rssi=smoothed_rssi,
            measured_power=ibeacon.measured_power if ibeacon is not None else None,
            advertised_tx_power=getattr(advertisement_data, 'tx_power', None),
            service_data={
                str(service_uuid): bytes(payload).hex().upper()
                for service_uuid, payload in service_data.items()
            },
            sample_count=smoother.count,
            seen_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info(
            'DETECTED protocol=%s name=%s address=%s uuid=%s major=%s minor=%s '
            'rssi=%d dBm smoothed=%.1f dBm samples=%d',
            reading.protocol,
            reading.device_name or 'unknown',
            reading.address or 'unknown',
            reading.uuid or 'not-advertised',
            reading.major if reading.major is not None else 'not-advertised',
            reading.minor if reading.minor is not None else 'not-advertised',
            reading.rssi,
            reading.smoothed_rssi,
            reading.sample_count,
        )
        if self.event_handler:
            self.event_handler(reading)

    async def _wait(self, timeout):
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def run(self):
        if BleakScanner is None:
            raise RuntimeError(
                'Bleak is not installed. Run: python -m pip install -r requirements.txt'
            )

        self._stop_event = asyncio.Event()
        started_at = time.monotonic()
        deadline = (
            started_at + self.config.duration_seconds
            if self.config.duration_seconds is not None
            else None
        )
        retry_delay = 1.0

        logger.info(
            'Starting %s BLE scan for GoHMoTech UUID %s. '
            'No pairing or connection will be attempted.',
            self.config.scan_mode,
            self.config.target_uuid,
        )

        while not self._stop_event.is_set():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                break

            session_seconds = self.config.restart_interval_seconds
            if remaining is not None:
                session_seconds = min(session_seconds, remaining)

            try:
                async with BleakScanner(
                    detection_callback=self._on_advertisement,
                    scanning_mode=self.config.scan_mode,
                    # Repeated packets are fresh sightings even when their
                    # payload/RSSI is unchanged. BlueZ suppresses them by default.
                    bluez={'filters': {'DuplicateData': True}},
                ):
                    logger.info('Bluetooth scanner is listening for advertisements.')
                    stopped = await self._wait(session_seconds)
                retry_delay = 1.0
                if stopped:
                    break
                logger.debug('Restarting BLE watcher after scheduled recovery interval.')
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error('BLE scan failed: %s', exc)
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                delay = retry_delay if remaining is None else min(retry_delay, remaining)
                logger.info('Retrying Bluetooth scan in %.1f seconds.', delay)
                if await self._wait(delay):
                    break
                retry_delay = min(retry_delay * 2, 30.0)

        logger.info('BLE scanner stopped.')
