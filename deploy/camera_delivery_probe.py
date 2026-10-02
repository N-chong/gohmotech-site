"""Timed authenticated probes of the real production camera; never prints secrets.

Run on the Pi with its production settings. Creates one short-lived session for
an existing administrator, deletes only that session on exit, and retains no JPEGs.
"""
import argparse
import base64
import concurrent.futures
import hashlib
import http.client
import importlib
import json
import os
import re
import sys
import subprocess
import threading
import time
import urllib.request
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.production")
import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from iot.goat_models import IPCamera


class CurlHTTP2Response:
    """HTTP/2 body via curl; session header goes over stdin, never process argv."""
    def __init__(self, url, headers, seconds):
        self.process = subprocess.Popen(['curl', '--http2', '--include', '--no-buffer', '--silent', '--show-error',
            '--connect-timeout', '8', '--max-time', str(seconds), '--config', '-'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        config = 'url = "' + url + '"\n' + ''.join('header = "' + key + ': ' + value.replace('\\', '\\\\').replace('"', '\\"') + '"\n' for key, value in headers.items())
        self.process.stdin.write(config.encode())
        self.process.stdin.close()
        status = self.process.stdout.readline().decode().split()
        if len(status) < 2:
            self.close()
            raise ValueError('curl did not receive HTTP response headers')
        self.protocol, self.status = status[0], int(status[1])
        self.headers = http.client.parse_headers(self.process.stdout)

    def read1(self, size):
        return self.process.stdout.read1(size)

    def close(self):
        self.process.stdout.close()
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=75)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--quality", type=int, default=75)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--reconnect", action="store_true")
    parser.add_argument("--transport", choices=['mjpeg', 'sse', 'jpeg'], default='mjpeg')
    parser.add_argument("--snapshot-samples", type=int, default=0)
    parser.add_argument("--http2", action='store_true', help='Use curl HTTP/2 for the public stage')
    args = parser.parse_args()
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    if user is None:
        raise SystemExit("No existing active administrator available for authorized probe")
    camera = IPCamera.objects.filter(is_active=True).first()
    if camera is None:
        raise SystemExit("No active camera")
    session = importlib.import_module(settings.SESSION_ENGINE).SessionStore()
    session["_auth_user_id"] = str(user.pk)
    session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    session["_auth_user_hash"] = user.get_session_auth_hash()
    session.set_expiry(600)
    session.save()
    headers = {"Host": "gohmotech.site", "X-Forwarded-Proto": "https",
               "Cookie": f"{settings.SESSION_COOKIE_NAME}={session.session_key}",
               "Accept-Encoding": "identity", "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"}
    path = f"/iot/camera/feed/{camera.pk}/?width={args.width}&quality={args.quality}&fps={args.fps}&transport={args.transport}"
    reference = []
    lock = threading.Lock()
    started = time.monotonic()

    def probe(label, base):
        events, arrivals, response_headers, errors = [], [], [], []
        total_bytes = 0
        connections = 2 if args.reconnect else 1
        for phase in range(connections):
            phase_start = time.monotonic()
            until = started + args.seconds * (phase + 1) / connections
            try:
                stage_headers = dict(headers)
                if label == "public":
                    stage_headers.pop("X-Forwarded-Proto", None)
                if args.transport == 'jpeg':
                    with requests.Session() as client:
                        last_log = time.monotonic()
                        while time.monotonic() < until:
                            requested = time.monotonic()
                            with client.get(base + path, headers=stage_headers, timeout=(8, 3)) as response:
                                response.raise_for_status()
                                if response.status_code == 204:
                                    time.sleep(.2)
                                    continue
                                jpeg = response.content
                                now = time.monotonic()
                                if response.headers.get('Content-Type') != 'image/jpeg':
                                    raise ValueError('Expected finite JPEG response')
                                sequence = int(response.headers['X-Frame-Sequence'])
                                captured_at = float(response.headers['X-Frame-Captured-At'])
                                total_bytes += len(jpeg)
                                response_headers[:] = [{k:v for k,v in response.headers.items() if k.lower() in {'content-type','content-length','cache-control','cf-cache-status','server'}}]
                                events.append({'t': round(now-started, 3), 'seq': sequence, 'hash': hashlib.sha256(jpeg).hexdigest(),
                                    'bytes': len(jpeg), 'lag': None, 'phase': phase, 'phase_elapsed': round(now-phase_start, 3),
                                    'capture_age': round(time.time()-captured_at, 3)})
                            if now-last_log >= 15:
                                print(json.dumps({'progress': label, 'frames':len(events), 'elapsed':round(now-started, 1),
                                                  'capture_age':events[-1]['capture_age']}), flush=True)
                                last_log = now
                            time.sleep(max(0, 1/args.fps - (time.monotonic()-requested)))
                    continue
                request = urllib.request.Request(base + path, headers=stage_headers)
                opened = CurlHTTP2Response(base + path, stage_headers, args.seconds + 12) if args.http2 and label == 'public' else urllib.request.urlopen(request, timeout=12)
                with opened as response:
                    response_headers.append({k: v for k, v in response.headers.items()
                                             if k.lower() in {"content-type", "content-encoding", "cache-control", "cf-cache-status", "cf-ray", "server", "transfer-encoding", "x-accel-buffering", "x-stream-started-at"}})
                    if hasattr(response, 'protocol'):
                        response_headers[-1]['protocol'] = response.protocol
                    expected = 'text/event-stream' if args.transport == 'sse' else 'multipart'
                    if response.status != 200 or expected not in response.headers.get("Content-Type", ""):
                        raise ValueError(f"Unexpected response {response.status}")
                    buffer = b""
                    last_log = time.monotonic()
                    while time.monotonic() < until:
                        chunk = response.read1(65536)
                        now = time.monotonic()
                        if not chunk:
                            errors.append("EOF")
                            break
                        arrivals.append((round(now - started, 3), len(chunk)))
                        total_bytes += len(chunk)
                        buffer += chunk
                        while True:
                            if args.transport == 'sse':
                                if b'\n\n' not in buffer:
                                    break
                                end = buffer.index(b'\n\n')
                                event, buffer = buffer[:end], buffer[end + 2:]
                                data = next((line[6:] for line in event.splitlines() if line.startswith(b'data: ')), None)
                                if data is None:
                                    continue
                                packet = json.loads(data)
                                jpeg = base64.b64decode(packet['jpeg'], validate=True)
                                sequence = int(packet['sequence'])
                                captured_at = float(packet['captured_at'])
                                length = len(jpeg)
                            else:
                                if b'\r\n\r\n' not in buffer:
                                    break
                                end = buffer.index(b"\r\n\r\n")
                                header = buffer[:end]
                                size = re.search(rb"Content-Length:\s*(\d+)", header, re.I)
                                seq = re.search(rb"X-Frame-Sequence:\s*(\d+)", header, re.I)
                                stamp = re.search(rb"X-Frame-Captured-At:\s*([\d.]+)", header, re.I)
                                if not size or not seq:
                                    raise ValueError("Missing multipart metadata")
                                length = int(size[1])
                                if len(buffer) < end + 4 + length:
                                    break
                                jpeg = buffer[end + 4:end + 4 + length]
                                buffer = buffer[end + 4 + length:]
                                sequence = int(seq[1])
                                captured_at = float(stamp[1]) if stamp else None
                            lag = None
                            with lock:
                                if label == "backend":
                                    reference.append((sequence, now))
                                elif reference:
                                    nearest = min(reference, key=lambda item: abs(item[0] - sequence))
                                    if abs(nearest[0] - sequence) <= 3:
                                        lag = round(now - nearest[1], 3)
                            events.append({"t": round(now - started, 3), "seq": sequence,
                                           "hash": hashlib.sha256(jpeg).hexdigest(), "bytes": length,
                                           "lag": lag, "phase": phase,
                                           "capture_age": round(time.time() - captured_at, 3) if captured_at is not None else None,
                                           "phase_elapsed": round(now - phase_start, 3)})
                        if now - last_log >= 15:
                            print(json.dumps({"progress": label, "elapsed": round(now-started, 1),
                                              "frames": len(events), "sequence": events[-1]["seq"] if events else None,
                                              "lag": events[-1]["lag"] if events else None}), flush=True)
                            last_log = now
            except Exception as error:
                errors.append(type(error).__name__ + ": " + str(error).split("http")[0])
                if hasattr(error, "headers"):
                    response_headers.append({k:v for k,v in error.headers.items()
                                             if k.lower() in {"server", "cf-ray", "cf-mitigated", "content-type"}})
        elapsed = time.monotonic() - started
        changes = sum(i == 0 or e["hash"] != events[i-1]["hash"] for i, e in enumerate(events))
        gaps = [events[i]["t"] - events[i-1]["t"] for i in range(1, len(events))]
        lags = sorted(e["lag"] for e in events if e["lag"] is not None)
        ages = sorted(e['capture_age'] for e in events if e['capture_age'] is not None)
        return {"stage": label, "seconds": round(elapsed, 2), "frames": len(events),
                "changing_frames": changes, "changing_fps": round(changes / elapsed, 2),
                "first_frame_seconds": events[0]["t"] if events else None,
                "reconnect_first_frame_seconds": next((e["phase_elapsed"] for e in events if e["phase"] == 1), None),
                "max_frame_gap_seconds": round(max(gaps, default=0), 3),
                "gaps_over_2_seconds": sum(g > 2 for g in gaps),
                "sequence_first_last": [events[0]["seq"], events[-1]["seq"]] if events else [],
                "lag_p50_p95_max_seconds": [lags[len(lags)//2], lags[int((len(lags)-1)*.95)], lags[-1]] if lags else [],
                "capture_age_p50_p95_max_seconds": [ages[len(ages)//2], ages[int((len(ages)-1)*.95)], ages[-1]] if ages else [],
                "megabits_per_second": round(total_bytes * 8 / elapsed / 1e6, 3),
                "mean_jpeg_bytes": round(sum(e["bytes"] for e in events)/len(events)) if events else None,
                "response_headers": response_headers, "errors": errors}
    try:
        if args.snapshot_samples:
            for label, base in [('nginx', 'http://127.0.0.1:8080'), ('public', 'https://gohmotech.site')]:
                results = []
                sample_headers = dict(headers)
                if label == 'public':
                    sample_headers.pop('X-Forwarded-Proto', None)
                for _ in range(args.snapshot_samples):
                    before = time.monotonic()
                    try:
                        request = urllib.request.Request(base + f'/iot/camera/snapshot/{camera.pk}/?diagnostic={time.time_ns()}', headers=sample_headers)
                        with urllib.request.urlopen(request, timeout=12) as response:
                            jpeg = response.read()
                            results.append({'status': response.status, 'bytes': len(jpeg),
                                            'seconds': round(time.monotonic()-before, 3),
                                            'hash': hashlib.sha256(jpeg).hexdigest()})
                    except Exception as error:
                        results.append({'error': type(error).__name__, 'seconds': round(time.monotonic()-before, 3)})
                print(json.dumps({'snapshot_stage': label, 'samples': results}), flush=True)
            return
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(probe, label, base) for label, base in
                       [("backend", "http://127.0.0.1:8010"), ("nginx", "http://127.0.0.1:8080"),
                        ("public", "https://gohmotech.site")]]
            for future in futures:
                print(json.dumps(future.result(), sort_keys=True), flush=True)
    finally:
        session.delete()


if __name__ == "__main__":
    main()
