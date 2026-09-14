"""Require an active farm role before entering any farm event stream."""

from channels.db import database_sync_to_async
from marketplace.auth import has_farm_access


class FarmWebSocketAccess:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        user = scope.get('user')
        allowed = bool(user and user.is_active) and await database_sync_to_async(has_farm_access)(user)
        if not allowed:
            await receive()
            await send({'type': 'websocket.close', 'code': 4403})
            return
        await self.app(scope, receive, send)
