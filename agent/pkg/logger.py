"""Структурный логгер (structlog).

Консоль: pretty (dev) либо JSON (LOG_FORMAT=json, прод). Файлы: `logs/app.jsonl` —
всё хронологически, `logs/error.jsonl` — WARNING и выше. Уровень — LOG_LEVEL.

Контекст: всё, что привязано через `bound(...)`/`bind(...)` (request_id, instance_id,
event_id, turn, task_id), попадает в каждую строку внутри блока — руками
прокидывать не нужно. Исключение сворачивается в `error="Type: msg"` одной
строкой, трейсбек остаётся отдельным полем.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

_LOG_DIR = Path("logs")
_LEVEL = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
_JSON_CONSOLE = os.environ.get("LOG_FORMAT", "").lower() == "json"


def _exc_summary(_logger, _method, event: dict) -> dict:
    """exc_info → error="Type: msg" (одна строка на причину; трейсбек — отдельно)."""
    exc = event.get("exc_info")
    if exc is True:
        exc = sys.exc_info()[1]
    elif isinstance(exc, tuple):
        exc = exc[1]
    if isinstance(exc, BaseException) and "error" not in event:
        event["error"] = f"{type(exc).__name__}: {exc}"
    return event


_CALLSITE = structlog.processors.CallsiteParameterAdder(
    [structlog.processors.CallsiteParameter.MODULE, structlog.processors.CallsiteParameter.LINENO],
    additional_ignores=[__name__],  # иначе callsite — этот файл, а не место вызова
)


def _callsite_for_warnings(_logger, method: str, event: dict) -> dict:
    """module:line только для WARNING+ — где искать, не платя за это на INFO."""
    if method in ("warning", "error", "critical", "exception"):
        return _CALLSITE(_logger, method, event)
    return event


_CONTEXT_KEYS = ("request_id", "instance_id", "event_id", "turn", "task_id")


def _context_first(_logger, _method, event: dict) -> dict:
    """Консоль: привязанный контекст перед полями записи — глаз ищет его в одном месте."""
    head = {k: event.pop(k) for k in _CONTEXT_KEYS if k in event}
    return {**head, **event}


def _short_time(_logger, _method, event: dict) -> dict:
    """Консоли хватает HH:MM:SS.mmm; дата — в файлах."""
    ts = event.get("timestamp")
    if isinstance(ts, str) and "T" in ts:
        event["timestamp"] = ts.split("T", 1)[1][:12]
    return event


# Общие процессоры — и для structlog-, и для stdlib-логгеров (uvicorn, langchain)
_shared = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    _exc_summary,
    _callsite_for_warnings,
]


def _setup() -> None:
    _LOG_DIR.mkdir(exist_ok=True)

    structlog.configure(
        processors=[*_shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        foreign_pre_chain=_shared,
    )

    console = logging.StreamHandler()
    if _JSON_CONSOLE:
        console.setFormatter(json_formatter)
    else:
        console.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    _short_time,
                    _context_first,
                    structlog.dev.ConsoleRenderer(sort_keys=False),
                ],
                foreign_pre_chain=_shared,
            )
        )

    app_file = RotatingFileHandler(_LOG_DIR / "app.jsonl", maxBytes=20_000_000, backupCount=3)
    app_file.setFormatter(json_formatter)
    err_file = RotatingFileHandler(_LOG_DIR / "error.jsonl", maxBytes=10_000_000, backupCount=3)
    err_file.setLevel(logging.WARNING)
    err_file.setFormatter(json_formatter)

    root = logging.getLogger()
    root.handlers = [console, app_file, err_file]
    root.setLevel(_LEVEL)

    # Сторонние логгеры: per-request debug HTTP-клиентов и «Failed to run command»
    # SDK OpenSandbox дублируют наши строки без контекста — молчат.
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("opensandbox").setLevel(logging.CRITICAL)


_setup()
get_logger = structlog.get_logger
# Контекст на блок кода / на время жизни таска: with bound(instance_id=1): ...
bound = structlog.contextvars.bound_contextvars
bind = structlog.contextvars.bind_contextvars
unbind = structlog.contextvars.unbind_contextvars
clear = structlog.contextvars.clear_contextvars
