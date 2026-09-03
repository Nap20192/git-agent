"""Сквозной trace_id (32 hex, uuid4 без дефисов) — одно имя поля `trace_id` на
hub/раннер/фронт. Живёт в structlog-contextvars: вешается на входе (Rabbit-сообщение
`traceId`, HTTP `X-Trace-Id`), дальше его несут логи, activity-кадры,
hub.activity.trace_id, метаданные Langfuse/LangSmith и заголовки вызовов в hub."""

from __future__ import annotations

import uuid

from structlog.contextvars import get_contextvars

HEADER = "X-Trace-Id"
FIELD = "trace_id"


def new_trace_id() -> str:
    return uuid.uuid4().hex


def is_valid(value: str | None) -> bool:
    return bool(value) and len(value) == 32 and all(c in "0123456789abcdefABCDEF" for c in value)


def accept(value: str | None) -> str:
    """Входящий id, если он в нашем формате (в нижнем регистре), иначе новый."""
    return value.lower() if value and is_valid(value) else new_trace_id()


def current_trace_id() -> str | None:
    """trace_id текущего контекста (contextvars), None вне хода/запроса."""
    value = get_contextvars().get(FIELD)
    return str(value) if value else None


def current_or_new() -> str:
    return current_trace_id() or new_trace_id()
