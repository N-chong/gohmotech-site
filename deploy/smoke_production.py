"""Read-only HTTP checks through the production loopback nginx origin."""

import time
import urllib.error
import urllib.request


checks = {
    "/marketplace/": 200,
    "/accounts/login/": 200,
    "/static/admin/css/base.css": 200,
    "/iot/api/actuators/esp32_commands/?device_id=smoke": 403,
    "/feeding/api/logs/servo-commands/?feeder_id=1": 403,
    "/media/seller_documents/missing.pdf": 404,
}

for path, expected in checks.items():
    actual = None
    for attempt in range(10):
        request = urllib.request.Request(
            "http://127.0.0.1:8080" + path,
            headers={"Host": "gohmotech.site"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                actual = response.status
        except urllib.error.HTTPError as exc:
            actual = exc.code
            exc.close()
        except urllib.error.URLError:
            actual = None
        if actual == expected:
            break
        if actual not in (None, 502, 503):
            break
        time.sleep(1)
    if actual != expected:
        raise SystemExit(f"FAIL {path}: expected {expected}, received {actual}")
    print(f"PASS {actual} {path}")

manifest_request = urllib.request.Request(
    "http://127.0.0.1:8080/static/manifest.webmanifest",
    headers={"Host": "gohmotech.site"},
)
with urllib.request.urlopen(manifest_request, timeout=10) as manifest_response:
    manifest_content_type = manifest_response.headers.get_content_type()
if manifest_content_type != "application/manifest+json":
    raise SystemExit(
        "FAIL /static/manifest.webmanifest: expected Content-Type "
        f"application/manifest+json, received {manifest_content_type}"
    )
print("PASS application/manifest+json /static/manifest.webmanifest")
