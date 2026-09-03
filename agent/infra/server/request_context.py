"""ASGI-middleware раннера: trace_id (сквозной X-Trace-Id от hub либо свой, pkg/trace)
в лог-контексте на всё время запроса, включая тело SSE-стрима; тот же id — в
заголовке ответа; access-строка одной записью. Чистый ASGI, а не BaseHTTPMiddleware:
тот снимает контекст до того, как StreamingResponse начнёт писать кадры."""

from __future__ import annotations

import time

from structlog.contextvars import bound_contextvars as bound

from pkg import trace
from pkg.logger import get_logger

log = get_logger(__name__)
_QUIET_PATHS = {"/health"}
_HEADER = trace.HEADER.lower().encode()


class RequestContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        trace_id = trace.accept(headers.get(_HEADER, b"").decode("latin-1"))
        status = 0
        started = time.monotonic()

        async def send_with_trace(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (_HEADER, trace_id.encode()),
                ]
            await send(message)

        with bound(trace_id=trace_id):
            try:
                await self.app(scope, receive, send_with_trace)
            finally:
                if scope["path"] not in _QUIET_PATHS:
                    log.info(
                        "http",
                        method=scope["method"],
                        path=scope["path"],
                        status=status,
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
