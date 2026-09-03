"""Человекочитаемое описание исключения: тип + текст + цепочка причин.

Одна функция для всех границ (логи, кадр run_failed, HTTP 500): str(exc) у
многих библиотек пуст или бесполезен, а причина сидит в __cause__.
"""

from __future__ import annotations

_MAX_CHAIN = 4


def describe(exc: BaseException, *, limit: int = 500) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen and len(parts) < _MAX_CHAIN:
        seen.add(id(cur))
        text = str(cur).strip()
        parts.append(f"{type(cur).__name__}: {text}" if text else type(cur).__name__)
        cur = cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)
    out = " ← caused by: ".join(parts)
    return out if len(out) <= limit else out[: limit - 1] + "…"
