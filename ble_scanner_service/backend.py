"""Non-blocking reporter for the GoHMoTech BLE ingestion API."""

import asyncio
from dataclasses import dataclass
import logging
import platform
import socket
import sys
from urllib.parse import urlparse

import requests


logger = logging.getLogger(__name__)
SCANNER_VERSION = '0.2.0'


class BackendAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendConfig:
    base_url: str
    receiver_id: str
    receiver_key: str
    request_timeout_seconds: float = 5.0
    queue_size: int = 100
    host_header: str | None = None

    def __post_init__(self):
        base_url = str(self.base_url).strip().rstrip('/')
        parsed = urlparse(base_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('BLE backend URL must be an absolute HTTP(S) URL.')
        if not str(self.receiver_id).strip():
            raise ValueError('BLE receiver ID cannot be empty.')
        if not self.receiver_key:
            raise ValueError('BLE receiver key cannot be empty.')
        if self.request_timeout_seconds <= 0:
            raise ValueError('Backend request timeout must be greater than zero.')
        if not 1 <= self.queue_size <= 10000:
            raise ValueError('Backend queue size must be between 1 and 10000.')
        if self.host_header:
            if parsed.hostname not in {'127.0.0.1', '::1', 'localhost'}:
                raise ValueError('A backend Host override requires a loopback URL.')
            if any(character.isspace() for character in self.host_header):
                raise ValueError('Backend Host cannot contain whitespace.')
        object.__setattr__(self, 'base_url', base_url)
        object.__setattr__(self, 'receiver_id', str(self.receiver_id).strip())


class BLEBackendReporter:
    """Send heartbeats and observations without blocking Bluetooth callbacks."""

    def __init__(self, config, assignment_handler=None):
        self.config = config
        self.assignment_handler = assignment_handler
        self._queue = asyncio.Queue(maxsize=config.queue_size)
        self._stop_event = None
        self._tasks = []
        self._heartbeat_interval_seconds = 5.0

    @property
    def headers(self):
        headers = {
            'X-Receiver-ID': self.config.receiver_id,
            'Authorization': f'Bearer {self.config.receiver_key}',
            'Content-Type': 'application/json',
        }
        if self.config.host_header:
            headers['Host'] = self.config.host_header
        return headers

    def _post_json_sync(self, path, payload):
        url = f'{self.config.base_url}/{path.lstrip("/")}'
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self.headers,
                timeout=self.config.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise BackendAPIError(f'Cannot reach BLE backend: {exc}') from exc

        try:
            body = response.json()
        except ValueError:
            body = {'detail': response.text[:300] or 'Invalid JSON response.'}
        if not response.ok:
            detail = body.get('detail', body) if isinstance(body, dict) else body
            raise BackendAPIError(
                f'BLE backend returned HTTP {response.status_code}: {detail}'
            )
        return body

    async def _post_json(self, path, payload):
        return await asyncio.to_thread(self._post_json_sync, path, payload)

    def _heartbeat_payload(self):
        system = platform.system().lower()
        scanner_platform = {
            'windows': 'windows',
            'linux': 'linux',
        }.get(system, 'other')
        return {
            'scanner_version': SCANNER_VERSION,
            'device_name': socket.gethostname(),
            'platform': scanner_platform,
            'metadata': {
                'python_version': platform.python_version(),
                'operating_system': platform.platform(),
                'executable': sys.executable,
            },
        }

    async def _send_heartbeat(self):
        response = await self._post_json('heartbeat/', self._heartbeat_payload())
        tracking_config = response.get('tracking_config') or {}
        interval = tracking_config.get('heartbeat_interval_seconds')
        if isinstance(interval, (int, float)) and interval > 0:
            self._heartbeat_interval_seconds = float(interval)
        beacons = response.get('beacons') or []
        if self.assignment_handler:
            self.assignment_handler(beacons)
        logger.info(
            'Backend heartbeat accepted for receiver %s; %d enabled beacon(s).',
            self.config.receiver_id,
            len(beacons),
        )
        return response

    async def _heartbeat_loop(self):
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._heartbeat_interval_seconds,
                )
                break
            except TimeoutError:
                pass

            try:
                await self._send_heartbeat()
            except BackendAPIError as exc:
                logger.warning('%s Scanning will continue.', exc)

    async def _observation_loop(self):
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                payload = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                continue

            try:
                response = await self._post_json('observations/', payload)
                goat = response.get('goat') or {}
                state = response.get('state') or {}
                logger.info(
                    'Backend updated goat=%s proximity=%s status=%s history_saved=%s',
                    goat.get('goat_id', 'unassigned'),
                    state.get('proximity', 'unknown'),
                    state.get('status', 'unknown'),
                    response.get('history_saved', False),
                )
            except BackendAPIError as exc:
                logger.warning('%s Observation was not persisted.', exc)
            finally:
                self._queue.task_done()

    async def start(self):
        if self._stop_event is not None:
            return
        self._stop_event = asyncio.Event()
        try:
            await self._send_heartbeat()
        except BackendAPIError as exc:
            logger.warning('%s Scanning will start in offline mode.', exc)
        self._tasks = [
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._observation_loop()),
        ]

    def enqueue(self, reading):
        payload = reading.to_dict() if hasattr(reading, 'to_dict') else dict(reading)
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                logger.warning(
                    'Backend queue full; discarded the oldest BLE observation.'
                )
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(payload)

    async def stop(self):
        if self._stop_event is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._queue.join(), timeout=10.0)
        except TimeoutError:
            logger.warning('Timed out while flushing BLE observations to the backend.')
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=self.config.request_timeout_seconds + 2,
            )
        except TimeoutError:
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self._stop_event = None
