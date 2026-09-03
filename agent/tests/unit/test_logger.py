"""pkg.logger: контекст `bound` и причина исключения попадают в каждую запись."""

import json
import logging

import structlog

from pkg import logger


def _capture(level: int = logging.INFO):
    records: list[str] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    h = _Handler()
    h.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
            foreign_pre_chain=logger._shared,
        )
    )
    root = logging.getLogger()
    root.addHandler(h)
    return records, lambda: root.removeHandler(h)


def test_bound_context_and_exc_summary():
    records, cleanup = _capture()
    log = logger.get_logger("test")
    try:
        with logger.bound(instance_id=7, turn="event"):
            try:
                raise ConnectionError("no route to host")
            except ConnectionError:
                log.warning("sandbox cmd failed", exc_info=True)
        log.info("outside")
    finally:
        cleanup()
    first, second = (json.loads(r) for r in records[-2:])
    assert first["instance_id"] == 7 and first["turn"] == "event"
    assert first["error"] == "ConnectionError: no route to host"
    assert first["module"] == "test_logger" and isinstance(first["lineno"], int)
    assert "instance_id" not in second  # контекст снят после блока
    assert "module" not in second  # callsite только для WARNING+
