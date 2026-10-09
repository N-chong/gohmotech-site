"""Read-only HTTP checks through the loopback nginx origin."""

import time
import urllib.error
import urllib.request

checks = {
    '/marketplace/': 200,
    '/accounts/login/': 200,
    '/static/admin/css/base.css': 200,
    '/iot/api/actuators/esp32_commands/?device_id=test': {401, 403},
    '/feeding/api/logs/servo-commands/?feeder_id=1': {401, 403},
    '/media/seller_documents/missing.pdf': 404,
}

for path, expected_statuses in checks.items():
    if isinstance(expected_statuses, int):
        expected_statuses = {expected_statuses}
    actual = None
    for attempt in range(10):
        request = urllib.request.Request(
            'http://127.0.0.1:8080' + path,
            headers={'Host': 'gohmotech.site'},
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
        expected_display = '/'.join(str(value) for value in sorted(expected_statuses))
        raise SystemExit(
            f'FAIL {path}: expected {expected_display}, received {actual}'
        )
    print(f'PASS {actual} {path}')
