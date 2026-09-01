"""Структурный логгер: pretty в консоль, JSON-строки в logs/<level>.jsonl (файл на уровень).

Использование:
    from pkg.logger import get_logger
    log = get_logger(__name__)
    log.info("repo scanned", repo="x", files=42)
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

_LOG_DIR = Path("logs")

# Общие процессоры — применяются и к structlog-, и к обычным stdlib-логам
_shared = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
]


def _setup() -> None:
    _LOG_DIR.mkdir(exist_ok=True)

    structlog.configure(
        processors=_shared + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console = logging.StreamHandler()
    console.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(),
            ],
            foreign_pre_chain=_shared,
        )
    )

    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=_shared,
    )

    handlers: list[logging.Handler] = [console]
    for name in ("debug", "info", "warning", "error", "critical"):
        levelno = getattr(logging, name.upper())
        h = RotatingFileHandler(
            _LOG_DIR / f"{name}.jsonl", maxBytes=10_000_000, backupCount=3
        )
        h.addFilter(lambda record, lv=levelno: record.levelno == lv)
        h.setFormatter(json_formatter)
        handlers.append(h)

    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(logging.INFO)


_setup()
get_logger = structlog.get_logger
