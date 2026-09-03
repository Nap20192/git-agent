"""ASGI-middleware раннера: request_id (сквозной X-Request-ID от hub либо свой)
в лог-контексте на всё время запроса, включая тело SSE-стрима; access-строка
одной записью. Чистый ASGI, а не BaseHTTPMiddleware: тот снимает контекст до
того, как StreamingResponse начнёт писать кадры."""

from __future__ import annotations

import secrets
import time

from structlog.contextvars import bound_contextvars as bound

from pkg.logger import get_logger

log = get_logger(__name__)
_QUIET_PATHS = {"/health"}


class RequestContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        request_id = headers.get(b"x-request-id", b"").decode("latin-1")[:64] or secrets.token_hex(
            6
        )
        status = 0
        started = time.monotonic()

        async def send_with_id(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        with bound(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            finally:
                if scope["path"] not in _QUIET_PATHS:
                    log.info(
                        "http",
                        method=scope["method"],
                        path=scope["path"],
                        status=status,
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
