"""Структурный логгер (structlog): pretty-консоль для людей, JSON — для машин.

- LOG_LEVEL (INFO) — порог; LOG_FORMAT=pretty|json — формат консоли, дефолт
  pretty на TTY и json в пайпе/контейнере. Файлы logs/<level>.jsonl — всегда JSON.
- Контекст хода (instance_id, event_id, …) вешается один раз через
  `structlog.contextvars.bound_contextvars()` в точке входа; дальше его несут ВСЕ
  логи ниже по стеку, включая stdlib-логи библиотек и дочерние asyncio-таски.
- uvicorn и warnings перенаправлены в этот же конвейер — один формат на процесс.
- Исключение логируй `log.exception(...)` ровно один раз, на границе, где оно
  обрабатывается; текст причины — `pkg.errors.describe`.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

_LOG_DIR = Path("logs")
_LEVEL = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
_TTY = sys.stderr.isatty()
_FORMAT = os.environ.get("LOG_FORMAT") or ("pretty" if _TTY else "json")

# Общие процессоры — применяются и к structlog-, и к обычным stdlib-логам
_shared = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.stdlib.PositionalArgumentsFormatter(),  # "%s"-аргументы stdlib (uvicorn access)
    structlog.stdlib.ExtraAdder(),  # logging.info(..., extra={...}) → поля
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.UnicodeDecoder(),
]

_json = [structlog.processors.dict_tracebacks, structlog.processors.JSONRenderer()]


def _formatter(renderers: list) -> logging.Formatter:
    return structlog.stdlib.ProcessorFormatter(
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderers],
        foreign_pre_chain=_shared,
    )


def _setup() -> None:
    _LOG_DIR.mkdir(exist_ok=True)
    structlog.configure(
        processors=[*_shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(
        _formatter(_json if _FORMAT == "json" else [structlog.dev.ConsoleRenderer(colors=_TTY)])
    )
    handlers: list[logging.Handler] = [console]
    for name in ("debug", "info", "warning", "error", "critical"):
        levelno = getattr(logging, name.upper())
        h = RotatingFileHandler(_LOG_DIR / f"{name}.jsonl", maxBytes=10_000_000, backupCount=3)
        h.addFilter(lambda record, lv=levelno: record.levelno == lv)
        h.setFormatter(_formatter(_json))
        handlers.append(h)

    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(_LEVEL)
    logging.captureWarnings(True)

    # uvicorn ставит свои хендлеры и не пропагирует — заворачиваем в наш конвейер
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers = []
        uv.propagate = True

    # Болтливые сторонние логгеры молчат до WARNING даже когда наш код в DEBUG
    for noisy in (
        "httpx",
        "httpcore",
        "opensandbox",
        "urllib3",
        "asyncio",
        "aiormq",
        "aio_pika",
        "psycopg",
        "psycopg.pool",
        "langsmith",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_setup()
get_logger = structlog.get_logger
