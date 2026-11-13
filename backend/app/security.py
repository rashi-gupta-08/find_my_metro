import json
import logging
import time
import uuid
from .config import settings

log = logging.getLogger("metro.requests")


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started, request_id = time.monotonic(), str(uuid.uuid4())
        # Enforce actual streamed size, not just the caller's Content-Length.
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunks.append(message)
            size += len(message.get("body", b""))
            if size > settings.max_request_bytes:
                await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"Request body is too large"}'})
                return
            if not message.get("more_body", False):
                break
        index = 0

        async def replay():
            nonlocal index
            if index < len(chunks):
                message = chunks[index]
                index += 1
                return message
            return await receive()

        async def secured(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend([(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                                (b"referrer-policy", b"strict-origin-when-cross-origin"),
                                (b"permissions-policy", b"geolocation=(self)"), (b"x-request-id", request_id.encode())])
                if scope["path"].startswith("/api"):
                    headers.append((b"cache-control", b"no-store"))
                if settings.app_env == "production":
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                log.info(json.dumps({"request_id": request_id, "method": scope["method"],
                                     "status": message["status"], "duration_ms": round(1000*(time.monotonic()-started))}))
            await send(message)

        await self.app(scope, replay, secured)
