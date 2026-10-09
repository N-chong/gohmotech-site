"""Read-only HTTP checks through the production loopback nginx origin."""

import time
import urllib.error
import urllib.request


checks = {
    "/marketplace/": 200,
    "/accounts/login/": 200,
    "/static/admin/css/base.css": 200,
    # Depending on the active DRF authenticator ordering, an anonymous device
    # request is correctly rejected as either unauthenticated (401) or
    # forbidden without the device key (403).
    "/iot/api/actuators/esp32_commands/?device_id=smoke": {401, 403},
    "/feeding/api/logs/servo-commands/?feeder_id=1": {401, 403},
    "/media/seller_documents/missing.pdf": 404,
}

for path, expected_statuses in checks.items():
    if isinstance(expected_statuses, int):
        expected_statuses = {expected_statuses}
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
        if actual in expected_statuses:
            break
        if actual not in (None, 502, 503):
            break
        time.sleep(1)
    if actual not in expected_statuses:
        expected_display = "/".join(str(value) for value in sorted(expected_statuses))
        raise SystemExit(
            f"FAIL {path}: expected {expected_display}, received {actual}"
        )
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
