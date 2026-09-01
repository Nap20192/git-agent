"""FIFO-admission на делегации: ограниченная конкуренция + ограниченная очередь.

asyncio.Semaphore в CPython будит ожидающих FIFO и (после фикса gh-90155)
перебуживает следующего, если разбуженный отменился — ручная deque со
slot-transfer из референса здесь доказуемо не нужна. Лимиты заморожены
конструктором: reconfigure-API отсутствует намеренно (hot-reload конфига не
должен рекламировать ёмкость, которой у контроллера нет).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class SubagentCapacityError(RuntimeError):
    pass


class SubagentCapacityRejected(SubagentCapacityError):
    pass


class SubagentCapacityTimeout(SubagentCapacityError):
    pass


class SubagentCapacity:
    def __init__(
        self,
        *,
        max_running: int = 3,
        max_queued: int = 8,
        queue_timeout_seconds: float = 300.0,
    ) -> None:
        self._sem = asyncio.Semaphore(max_running)
        self._max_running = max_running
        self._max_queued = max_queued
        self._queue_timeout = queue_timeout_seconds
        self._queued = 0

    @property
    def max_running(self) -> int:
        return self._max_running

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        if self._sem.locked() and self._queued >= self._max_queued:
            raise SubagentCapacityRejected(f"admission queue is full ({self._max_queued} waiting)")
        self._queued += 1
        try:
            try:
                async with asyncio.timeout(self._queue_timeout):
                    await self._sem.acquire()
            except TimeoutError:
                raise SubagentCapacityTimeout(f"no slot within {self._queue_timeout}s") from None
            # CancelledError пробрасывается как есть — отмена не должна
            # выглядеть как retryable-ошибка admission
        finally:
            self._queued -= 1
        try:
            yield
        finally:
            self._sem.release()
