"""Short lived browser presence for farm accounts."""

import time
import uuid
from datetime import datetime, timezone

from .live_detection import redis_client

PREFIX = "gohmotech:active-users:v1"
PRESENCE_TTL = 40


def _token_key(token):
    return f"{PREFIX}:token:{token}"


def heartbeat(token, user_id, client=None):
    token = str(uuid.UUID(token))
    client = client or redis_client()
    expires_at = time.time() + PRESENCE_TTL
    client.set(_token_key(token), str(user_id), ex=PRESENCE_TTL)
    client.zadd(f"{PREFIX}:tokens", {token: expires_at})
    client.expire(f"{PREFIX}:tokens", PRESENCE_TTL + 60)


def leave(token, user_id, client=None):
    token = str(uuid.UUID(token))
    client = client or redis_client()
    if client.get(_token_key(token)) != str(user_id):
        return
    client.delete(_token_key(token))
    client.zrem(f"{PREFIX}:tokens", token)


def active_accounts(client=None):
    """Return account IDs with one row per user, regardless of open tabs."""
    client = client or redis_client()
    tokens_key = f"{PREFIX}:tokens"
    client.zremrangebyscore(tokens_key, "-inf", time.time())
    tokens = client.zrange(tokens_key, 0, -1, withscores=True)
    if not tokens:
        return {}
    owners = client.mget([_token_key(token) for token, _ in tokens])
    accounts = {}
    for (token, expires_at), owner in zip(tokens, owners):
        if owner is None:
            client.zrem(tokens_key, token)
            continue
        try:
            user_id = int(owner)
        except (TypeError, ValueError):
            client.zrem(tokens_key, token)
            continue
        last_signal = datetime.fromtimestamp(expires_at - PRESENCE_TTL, tz=timezone.utc)
        row = accounts.setdefault(user_id, {"pages": 0, "last_signal": last_signal})
        row["pages"] += 1
        row["last_signal"] = max(row["last_signal"], last_signal)
    return accounts
