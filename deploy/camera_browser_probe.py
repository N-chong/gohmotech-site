"""Real Chromium/public HTTPS camera rendering check on the production Pi.

Requires websocket-client in /tmp/gohmotech-browser-tools, not in production.
Temporary browser profile/session only. Does not enable AI or mutate camera settings.
"""
import argparse
from collections import Counter
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, "/tmp/gohmotech-browser-tools")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.production")
import django
django.setup()
import websocket
from django.conf import settings
from django.contrib.auth import get_user_model
from iot.goat_models import IPCamera


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=75)
    parser.add_argument("--mobile", action="store_true")
    parser.add_argument("--lifecycle", action="store_true")
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument('--jpeg-fixture', action='store_true')
    parser.add_argument('--http2-browser', action='store_true', help='Diagnostic only: disable Chromium HTTP/3')
    args = parser.parse_args()
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    camera = IPCamera.objects.filter(is_active=True).first()
    session = importlib.import_module(settings.SESSION_ENGINE).SessionStore()
    session.update({"_auth_user_id": str(user.pk), "_auth_user_backend": "django.contrib.auth.backends.ModelBackend",
                    "_auth_user_hash": user.get_session_auth_hash()})
    session.set_expiry(600)
    session.save()
    browser = None
    ws = None
    try:
        with tempfile.TemporaryDirectory(prefix="gohmotech-camera-browser-") as profile:
            browser = subprocess.Popen(["chromium", "--headless", "--no-sandbox", "--disable-gpu",
                "--no-first-run", "--disable-dev-shm-usage", "--password-store=basic", "--use-mock-keychain", "--remote-debugging-port=0",
                "--remote-allow-origins=http://localhost", f"--user-data-dir={profile}",
                *(['--disable-quic'] if args.http2_browser else []), "about:blank"],
                stdout=subprocess.DEVNULL, stderr=None)
            port_file = Path(profile) / "DevToolsActivePort"
            deadline = time.monotonic() + 20
            while not port_file.exists() and time.monotonic() < deadline:
                time.sleep(.2)
            if not port_file.exists():
                raise RuntimeError("Chromium debugging endpoint did not start")
            port = port_file.read_text().splitlines()[0]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as response:
                target = next(t for t in json.load(response) if t["type"] == "page")
            ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=10,
                                             origin="http://localhost")
            counter = 0
            errors = []
            protocols = []
            def call(method, params=None):
                nonlocal counter
                counter += 1
                ws.send(json.dumps({"id": counter, "method": method, "params": params or {}}))
                while True:
                    message = json.loads(ws.recv())
                    if message.get("method") == "Runtime.exceptionThrown":
                        errors.append(message["params"]["exceptionDetails"].get("text", "exception"))
                    if message.get('method') == 'Network.responseReceived':
                        response = message['params']['response']
                        if '/camera/feed/' in response['url']:
                            protocols.append({'protocol': response['protocol'], 'status': response['status'], 'mime': response['mimeType']})
                    if message.get("id") == counter:
                        if "error" in message:
                            raise RuntimeError(message["error"])
                        return message.get("result", {})
            call("Page.enable")
            call("Runtime.enable")
            call("Network.enable")
            call("Page.addScriptToEvaluateOnNewDocument", {"source": """
                window.cameraTestReaders = new Set();
                const originalFetch = window.fetch.bind(window);
                window.fetch = async (...args) => {
                    const response = await originalFetch(...args);
                    if (response.url.includes('/camera/feed/') && response.body) {
                        const getReader = response.body.getReader.bind(response.body);
                        response.body.getReader = () => {
                            const reader = getReader();
                            window.cameraTestReaders.add(reader);
                            const cancel = reader.cancel.bind(reader);
                            reader.cancel = (...values) => {
                                window.cameraTestReaders.delete(reader);
                                return cancel(...values);
                            };
                            return reader;
                        };
                    }
                    return response;
                };
                window.cameraPixels = {changes: 0, loads: 0, hash: null};
                document.addEventListener('load', event => {
                    const img = event.target;
                    if (!(img instanceof HTMLImageElement) || !img.hasAttribute('data-live-camera')) return;
                    const canvas = document.createElement('canvas'); canvas.width = 64; canvas.height = 36;
                    const ctx = canvas.getContext('2d', {willReadFrequently: true});
                    ctx.drawImage(img, 0, 0, 64, 36);
                    const pixels = ctx.getImageData(0, 0, 64, 36).data;
                    let hash = 2166136261;
                    for (const byte of pixels) hash = Math.imul(hash ^ byte, 16777619) >>> 0;
                    window.cameraPixels.loads++;
                    if (hash !== window.cameraPixels.hash) window.cameraPixels.changes++;
                    window.cameraPixels.hash = hash;
                }, true);
            """})
            call("Network.setCookie", {"name": settings.SESSION_COOKIE_NAME, "value": session.session_key,
                "url": "https://gohmotech.site", "secure": True, "httpOnly": True, "sameSite": "Lax"})
            call("Emulation.setDeviceMetricsOverride", {"width": 390 if args.mobile else 1366,
                "height": 844 if args.mobile else 900, "deviceScaleFactor": 3 if args.mobile else 1,
                "mobile": args.mobile})
            if args.mobile:
                call("Emulation.setCPUThrottlingRate", {"rate": 4})
            url = f"https://gohmotech.site/iot/cameras/{camera.pk}/"
            print(json.dumps({"browser": "mobile-emulation" if args.mobile else "desktop", "url": url}), flush=True)
            if args.fixture or args.jpeg_fixture:
                if args.jpeg_fixture:
                    call('Runtime.evaluate', {'expression': 'window.fixtureJPEG = true'})
                call("Runtime.evaluate", {"expression": (Path(__file__).parent / 'camera-sse-browser-fixture.js').read_text()})
                call("Runtime.evaluate", {"expression": (Path(__file__).resolve().parents[1] / 'static/js/live-camera.js').read_text()})
            else:
                call("Page.navigate", {"url": url})
            start = time.monotonic()
            samples = []
            offline = returned = False
            while time.monotonic() - start < args.seconds:
                elapsed = time.monotonic() - start
                if args.lifecycle and elapsed > 25 and not offline:
                    call("Network.emulateNetworkConditions", {"offline": True, "latency": 0,
                         "downloadThroughput": -1, "uploadThroughput": -1})
                    call("Runtime.evaluate", {"expression": "Promise.all([...window.cameraTestReaders].map(r => r.cancel()))", "awaitPromise": True})
                    offline = True
                    print('{"event":"network_offline"}', flush=True)
                if args.lifecycle and elapsed > 35 and offline and not returned:
                    call("Network.emulateNetworkConditions", {"offline": False, "latency": 0,
                         "downloadThroughput": -1, "uploadThroughput": -1})
                    returned = True
                    print('{"event":"network_restored"}', flush=True)
                result = call("Runtime.evaluate", {"expression": "JSON.stringify((()=>{const i=document.querySelector('[data-live-camera]'); if(i){i.scrollIntoView({block:'center'});return {state:i.dataset.liveState,frames:Number(i.dataset.framesDisplayed||0),seq:i.dataset.frameSequence,age:i.dataset.frameAgeSeconds,width:i.naturalWidth,height:i.naturalHeight,fps:i.dataset.previewFps,transport:i.dataset.transport,pixelChanges:window.cameraPixels?.changes,pixelLoads:window.cameraPixels?.loads,fixture:window.fixtureStats}}return {ready:document.readyState,path:location.pathname};})())", "returnByValue": True})
                value = json.loads(result["result"].get("value", "{}"))
                value["seconds"] = round(elapsed, 2)
                samples.append(value)
                print(json.dumps(value), flush=True)
                time.sleep(5)
            if args.lifecycle:
                call("Page.navigate", {"url": "https://gohmotech.site/iot/cameras/"})
                time.sleep(3)
                call("Page.navigate", {"url": url})
                time.sleep(10)
                result = call("Runtime.evaluate", {"expression": "JSON.stringify((()=>{const i=document.querySelector('[data-live-camera]');return i?{state:i.dataset.liveState,frames:i.dataset.framesDisplayed,seq:i.dataset.frameSequence}:{};})())", "returnByValue": True})
                print(json.dumps({"navigation_return": json.loads(result["result"].get("value", "{}"))}), flush=True)
            print(json.dumps({"browser_summary": {"first_frame_seconds": next((s["seconds"] for s in samples if s.get("frames",0)>0), None),
                "frames_displayed": samples[-1].get("frames",0), "errors": errors,
                "protocol_counts": dict(Counter(f"{p['protocol']} {p['status']} {p['mime']}" for p in protocols))}}), flush=True)
            if args.fixture or args.jpeg_fixture:
                final = samples[-1]
                expected = 'jpeg-poll' if args.jpeg_fixture else 'sse'
                if not (final.get('frames', 0) > 5 and final.get('fps') == '4' and final.get('transport') == expected and final.get('fixture', {}).get('maxActive') == 1):
                    raise RuntimeError('Fragmented SSE/stale-frame fixture failed')
                print(json.dumps({'fixture': expected, 'result': 'PASS'}), flush=True)
    finally:
        if ws:
            ws.close()
        if browser:
            browser.terminate()
            try:
                browser.wait(timeout=10)
            except subprocess.TimeoutExpired:
                browser.kill()
                browser.wait()
        session.delete()


if __name__ == "__main__":
    main()
