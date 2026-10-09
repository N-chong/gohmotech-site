"""Read-only verification of the deployed tutorial schema, pages, and assets."""
import hashlib
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.production")

import django

django.setup()

from django.conf import settings
from django.db import connection


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


opener = urllib.request.build_opener(NoRedirect)


def fetch(path):
    request = urllib.request.Request(
        "http://127.0.0.1:8080" + path, headers={"Host": "gohmotech.site"}
    )
    try:
        response = opener.open(request, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


with connection.cursor() as cursor:
    tables = connection.introspection.table_names(cursor)
    if "dashboard_onboardingprogress" not in tables:
        raise SystemExit("FAIL: onboarding database table is missing")
print("PASS onboarding database table exists")

assets = [
    ("css/onboarding.css", "static/css/onboarding.css"),
    ("js/onboarding.js", "static/js/onboarding.js"),
    ("marketplace/seller-welcome.css", "marketplace/static/marketplace/seller-welcome.css"),
]
assets.extend(
    (f"images/onboarding/{image.name}", str(image))
    for image in sorted((Path(settings.BASE_DIR) / "static/images/onboarding").glob("goat_*.png"))
)
for relative, source in assets:
    status, headers, body = fetch("/static/" + relative)
    expected = (Path(settings.BASE_DIR) / source).read_bytes()
    if status != 200 or hashlib.sha256(body).digest() != hashlib.sha256(expected).digest():
        raise SystemExit(f"FAIL: deployed asset does not match source: {relative} ({status})")
    print(f"PASS deployed asset matches source: {relative}")

status, headers, body = fetch("/marketplace/")
if status != 200 or b"marketplace/seller-welcome.css" not in body:
    raise SystemExit("FAIL: live marketplace is not using the updated base template")
if b'id="seller-welcome-title"' in body:
    raise SystemExit("FAIL: seller approval banner is visible to an anonymous visitor")
print("PASS updated marketplace template; anonymous visitor sees no seller banner")

status, headers, body = fetch("/onboarding/state/")
if status != 302 or "/accounts/login/" not in headers.get("Location", ""):
    raise SystemExit(f"FAIL: onboarding endpoint must require login ({status})")
print("PASS deployed onboarding endpoint requires login")
