"""In-memory StreamBridge: журнал событий на ран + реплей по курсору.

Контракт пробелов: получив StreamGap, подписчик перечитывает durable-историю
через RunStore.list_events_after и переподписывается с last_event_id=None;
дедупликация — на стороне вызывающего.
# ponytail: live- и durable-курсоры раздельны; унифицировать на run_events.id,
# если понадобится бесшовный reconnect UX.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pkg.logger import get_logger

log = get_logger(__name__)

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15.0
MAX_HEARTBEAT_INTERVAL_SECONDS = 300.0

_EVENT_ID_RE = re.compile(r"\d+-(\d+)")


@dataclass(frozen=True)
class StreamEvent:
    id: str
    event: str
    data: Any


@dataclass(frozen=True)
class StreamGap:
    """Курсор подписчика больше не покрывается retained-буфером."""

    requested_event_id: str | None
    earliest_available_event_id: str | None
    latest_available_event_id: str | None


HEARTBEAT_SENTINEL = StreamEvent(id="", event="__heartbeat__", data=None)
END_SENTINEL = StreamEvent(id="", event="__end__", data=None)
type StreamItem = StreamEvent | StreamGap


@dataclass
class _RunStream:
    events: list[StreamEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    ended: bool = False
    start_offset: int = 0


class MemoryStreamBridge:
    """Журнал событий в памяти процесса; события живут в окне maxsize."""

    def __init__(
        self,
        *,
        maxsize: int = 512,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        if not (0 < heartbeat_interval <= MAX_HEARTBEAT_INTERVAL_SECONDS):
            raise ValueError(f"heartbeat_interval must be in (0, {MAX_HEARTBEAT_INTERVAL_SECONDS}]")
        self._maxsize = max(1, maxsize)
        self._heartbeat_interval = float(heartbeat_interval)
        self._streams: dict[int, _RunStream] = {}
        self._counters: dict[int, int] = {}

    def _get_or_create(self, run_id: int) -> _RunStream:
        if run_id not in self._streams:
            self._streams[run_id] = _RunStream()
            self._counters[run_id] = 0
        return self._streams[run_id]

    def _next_id(self, run_id: int) -> str:
        seq = self._counters.get(run_id, 0)
        self._counters[run_id] = seq + 1
        return f"{int(time.time() * 1000)}-{seq}"

    @staticmethod
    def _parse_seq(event_id: str) -> int | None:
        match = _EVENT_ID_RE.fullmatch(event_id)
        return int(match.group(1)) if match else None

    @staticmethod
    def _make_gap(stream: _RunStream, requested: str | None) -> StreamGap:
        return StreamGap(
            requested_event_id=requested,
            earliest_available_event_id=stream.events[0].id if stream.events else None,
            latest_available_event_id=stream.events[-1].id if stream.events else None,
        )

    def _resolve_start(self, stream: _RunStream, last_event_id: str | None) -> int | StreamGap:
        if last_event_id is None:
            return stream.start_offset
        # seq в id == абсолютный офсет события: курсор находится арифметикой за
        # O(1) и проверяется по id (timestamp-часть ловит стейл-курсор от
        # прошлой инкарнации стрима после cleanup). Ниже вотермарки — StreamGap
        # (консервативно); неизвестный id на/выше вотермарки — реплей с
        # раннего (лениво, с warning).
        seq = self._parse_seq(last_event_id)
        if seq is not None:
            if seq < stream.start_offset:
                return self._make_gap(stream, last_event_id)
            local = seq - stream.start_offset
            if 0 <= local < len(stream.events) and stream.events[local].id == last_event_id:
                return stream.start_offset + local + 1  # resume эксклюзивен
        if stream.events:
            log.warning(
                "last_event_id not in retained buffer; replaying from earliest",
                last_event_id=last_event_id,
            )
        return stream.start_offset

    async def publish(self, run_id: int, event: str, data: Any) -> None:
        stream = self._get_or_create(run_id)
        entry = StreamEvent(id=self._next_id(run_id), event=event, data=data)
        async with stream.condition:
            stream.events.append(entry)
            if len(stream.events) > self._maxsize:
                overflow = len(stream.events) - self._maxsize
                del stream.events[:overflow]
                stream.start_offset += overflow
            stream.condition.notify_all()

    async def publish_end(self, run_id: int) -> None:
        stream = self._get_or_create(run_id)
        async with stream.condition:
            stream.ended = True
            stream.condition.notify_all()

    async def subscribe(
        self,
        run_id: int,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float | None = None,
    ) -> AsyncIterator[StreamItem]:
        hb = self._heartbeat_interval if heartbeat_interval is None else heartbeat_interval
        stream = self._get_or_create(run_id)
        async with stream.condition:
            start = self._resolve_start(stream, last_event_id)
        if isinstance(start, StreamGap):
            yield start
            return

        next_offset = start
        cursor = last_event_id
        while True:
            should_stop = False
            async with stream.condition:
                if next_offset < stream.start_offset:
                    log.warning(
                        "subscriber fell behind retained buffer", run_id=run_id, offset=next_offset
                    )
                    entry: StreamItem = self._make_gap(stream, cursor)
                    should_stop = True
                else:
                    local = next_offset - stream.start_offset
                    if 0 <= local < len(stream.events):
                        entry = stream.events[local]
                        next_offset += 1
                        cursor = entry.id
                    elif stream.ended:
                        # ended проверяется только после осушения хвоста буфера
                        entry = END_SENTINEL
                    else:
                        try:
                            # wait_for внутри `async with condition` — таймаут
                            # сам перезахватывает лок; не «модернизировать».
                            await asyncio.wait_for(stream.condition.wait(), timeout=hb)
                        except TimeoutError:
                            entry = HEARTBEAT_SENTINEL
                        else:
                            continue

            if entry is END_SENTINEL:
                yield END_SENTINEL
                return
            yield entry  # вне лока
            if should_stop:
                return

    async def cleanup(self, run_id: int, *, delay: float = 0) -> None:
        # identity-aware: за время delay ран могли возобновить — новая
        # инкарнация стрима не должна быть снесена отложенной уборкой старой
        snapshot = self._streams.get(run_id)
        if delay > 0:
            await asyncio.sleep(delay)
            if snapshot is not None and self._streams.get(run_id) is not snapshot:
                return
        self._streams.pop(run_id, None)
        self._counters.pop(run_id, None)

    async def close(self) -> None:
        self._streams.clear()
        self._counters.clear()
