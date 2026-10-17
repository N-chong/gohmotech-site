import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from .user_presence import active_accounts, heartbeat, leave
from .views import active_users_view, user_presence_control


class MemoryPresenceRedis:
    def __init__(self):
        self.values = {}
        self.scores = {}

    def set(self, key, value, ex=None):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)

    def zadd(self, key, values):
        self.scores.setdefault(key, {}).update(values)

    def zrem(self, key, member):
        self.scores.get(key, {}).pop(member, None)

    def zremrangebyscore(self, key, lower, upper):
        for member, score in list(self.scores.get(key, {}).items()):
            if score <= upper:
                self.zrem(key, member)

    def zrange(self, key, start, end, withscores=False):
        values = sorted(self.scores.get(key, {}).items(), key=lambda item: item[1])
        return values if withscores else [member for member, _ in values]

    def mget(self, keys):
        return [self.get(key) for key in keys]

    def expire(self, key, seconds):
        return True


class UserPresenceTests(SimpleTestCase):
    @patch("ml_models.user_presence.time.time", return_value=1000)
    def test_multiple_pages_count_as_one_account(self, _clock):
        client = MemoryPresenceRedis()
        first = "11111111-1111-4111-8111-111111111111"
        second = "22222222-2222-4222-8222-222222222222"
        heartbeat(first, 7, client)
        heartbeat(second, 7, client)

        self.assertEqual(active_accounts(client)[7]["pages"], 2)
        leave(first, 8, client)
        self.assertEqual(active_accounts(client)[7]["pages"], 2)
        leave(first, 7, client)
        self.assertEqual(active_accounts(client)[7]["pages"], 1)

    @patch("ml_models.user_presence.time.time")
    def test_presence_expires_after_missed_heartbeats(self, clock):
        client = MemoryPresenceRedis()
        clock.return_value = 1000
        heartbeat("11111111-1111-4111-8111-111111111111", 7, client)
        clock.return_value = 1041

        self.assertEqual(active_accounts(client), {})

    def test_operator_cannot_see_named_active_users(self):
        request = RequestFactory().get("/ml/active-users/?format=json")
        request.user = SimpleNamespace(
            is_authenticated=True, is_active=True, is_staff=False,
            is_superuser=False,
            groups=SimpleNamespace(values_list=lambda *args, **kwargs: ["Farm Operators"]),
        )

        with self.assertRaises(PermissionDenied):
            active_users_view(request)

    def test_farm_owner_cannot_see_named_active_users(self):
        request = RequestFactory().get("/ml/active-users/?format=json")
        request.user = SimpleNamespace(
            is_authenticated=True, is_active=True, is_staff=False,
            is_superuser=False,
            groups=SimpleNamespace(values_list=lambda *args, **kwargs: ["Farm Owners"]),
        )

        with self.assertRaises(PermissionDenied):
            active_users_view(request)

    @patch("ml_models.user_presence.heartbeat")
    def test_operator_activity_is_recorded_under_own_account(self, record):
        token = "11111111-1111-4111-8111-111111111111"
        request = RequestFactory().post(
            "/ml/api/user-presence/",
            data=json.dumps({"action": "view", "token": token}),
            content_type="application/json",
        )
        request.user = SimpleNamespace(
            pk=17, is_authenticated=True, is_active=True, is_staff=False,
            is_superuser=False,
            groups=SimpleNamespace(values_list=lambda *args, **kwargs: ["Farm Operators"]),
        )

        response = user_presence_control(request)

        self.assertEqual(response.status_code, 200)
        record.assert_called_once_with(token, 17)

    @patch("ml_models.views.get_user_model")
    @patch("ml_models.user_presence.active_accounts")
    def test_admin_sees_distinct_account_count(self, active, user_model):
        active.return_value = {7: {
            "pages": 2, "last_signal": datetime(2026, 10, 13, tzinfo=timezone.utc),
        }}
        account = SimpleNamespace(
            pk=7, is_authenticated=True, is_active=True, is_staff=True,
            is_superuser=False, get_full_name=lambda: "Farm Admin",
            get_username=lambda: "admin",
        )
        user_model.return_value.objects.filter.return_value = [account]
        request = RequestFactory().get("/ml/active-users/?format=json")
        request.user = account

        response = active_users_view(request)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["users"][0]["pages"], 2)
