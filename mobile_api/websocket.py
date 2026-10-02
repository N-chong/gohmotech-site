from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.core import signing

from .views import TICKET_SALT


@database_sync_to_async
def ticket_user(raw_ticket):
    try:
        payload = signing.loads(raw_ticket, salt=TICKET_SALT, max_age=60)
    except signing.BadSignature:
        return None
    if payload.get("purpose") != "websocket":
        return None
    return get_user_model().objects.filter(pk=payload.get("user_id"), is_active=True).first()


class MobileTicketAuthMiddleware:
    """Accept a short-lived signed ticket without exposing the API token."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not getattr(scope.get("user"), "is_authenticated", False):
            query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
            raw_ticket = query.get("ticket", [None])[0]
            if raw_ticket:
                user = await ticket_user(raw_ticket)
                if user is not None:
                    scope["user"] = user
        return await self.app(scope, receive, send)
