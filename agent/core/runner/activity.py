"""Activity-кадры хода (тикет 012): граф Рана «Лид → Сабагенты» в Playground.

Контракт кадра — ActivityEvent в backend/docs/openapi.yaml (camelCase):
{kind, taskId?, description?, status?, findingsCount?, ts}. Коллектор — чистое
свёртывание стрим-чанков графа в кадры; фид — live-буфер хода с подписчиками
(SSE runner_api) поверх персиста в hub.activity.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

# терминальные task_*-события custom-стрима → (kind, status) кадра
_TERMINAL = {
    "task_completed": ("task_finished", "done"),
    "task_failed": ("task_failed", "failed"),
    "task_timed_out": ("task_failed", "timeout"),
    "task_cancelled": ("task_failed", "failed"),
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class ActivityCollector:
    """(mode, serialized chunk) → activity-кадры; держит счётчик Находок Лида
    и статусы Сабагентов (queued до первого прогресс-события)."""

    def __init__(self) -> None:
        self.findings = 0
        self._tasks: dict[str, str] = {}  # task_id -> status кадра

    def _frame(self, kind: str, **fields: Any) -> dict[str, Any]:
        return {"kind": kind, "ts": _now(), **{k: v for k, v in fields.items() if v is not None}}

    def run_started(self) -> dict[str, Any]:
        return self._frame("run_started")

    def run_finished(self) -> dict[str, Any]:
        return self._frame("run_finished", findingsCount=self.findings)

    def run_failed(self, error: Any) -> dict[str, Any]:
        return self._frame("run_failed", description=str(error)[:500], findingsCount=self.findings)

    def frames(self, mode: str, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        if mode == "custom":
            return self._custom(data)
        if mode == "updates":
            return self._updates(data)
        return []

    def _custom(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        dtype = str(data.get("type", ""))
        task_id = data.get("task_id")
        if not task_id:
            return []
        if dtype == "task_started":
            self._tasks[task_id] = "queued"
            return [
                self._frame(
                    "task_started",
                    taskId=task_id,
                    description=data.get("description"),
                    status="queued",
                )
            ]
        if dtype == "task_running":
            if self._tasks.get(task_id) != "queued":
                return []  # прогресс уже working — не спамим кадрами на каждый шаг
            self._tasks[task_id] = "working"
            return [self._frame("task_started", taskId=task_id, status="working")]
        if dtype in _TERMINAL:
            kind, status = _TERMINAL[dtype]
            self._tasks[task_id] = status
            findings = data.get("findings")
            return [
                self._frame(
                    kind,
                    taskId=task_id,
                    status=status,
                    description=data.get("error"),
                    findingsCount=len(findings) if isinstance(findings, list) else None,
                )
            ]
        return []

    def _updates(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = []
        for node, update in data.items():
            messages = update.get("messages") if isinstance(update, dict) else None
            for msg in messages or []:
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") == "ai":
                    self.findings += sum(
                        1 for c in msg.get("tool_calls") or [] if c.get("name") == "report_finding"
                    )
                # самоотчёт Сабагента: ToolMessage task-тула, парный task_id
                if (
                    msg.get("type") == "tool"
                    and msg.get("name") == "task"
                    and msg.get("tool_call_id")
                ):
                    frames.append(
                        self._frame(
                            "task_report",
                            taskId=msg["tool_call_id"],
                            description=str(msg.get("content") or ""),
                        )
                    )
            frames.append(
                self._frame("node", description=node, status="done", findingsCount=self.findings)
            )
        return frames


Persist = Callable[[int, dict[str, Any]], Awaitable[None]]


class ActivityTurn:
    """Один ход: seq-нумерация, персист, буфер и live-подписчики."""

    def __init__(self, event_id: int | None, persist: Persist) -> None:
        self.event_id = event_id
        self.done = False
        self._persist = persist
        self._seq = 0
        self._frames: list[dict[str, Any]] = []
        self._subscribers: list[asyncio.Queue] = []

    async def emit(self, frame: dict[str, Any]) -> None:
        self._seq += 1
        await self._persist(self._seq, frame)
        self._frames.append(frame)
        for queue in self._subscribers:
            queue.put_nowait(frame)

    def close(self) -> None:
        self.done = True
        for queue in self._subscribers:
            queue.put_nowait(None)

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Реплей буфера + live до конца хода (подписка и снапшот атомарны)."""
        queue: asyncio.Queue = asyncio.Queue()
        if not self.done:
            self._subscribers.append(queue)
        snapshot = list(self._frames)
        try:
            for frame in snapshot:
                yield frame
            if self.done and queue not in self._subscribers:
                return
            while True:
                frame = await queue.get()
                if frame is None:
                    return
                yield frame
        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)


class ActivityFeed:
    """Live-ходы per Экземпляр; завершённые ходы читаются из hub.activity."""

    def __init__(self) -> None:
        self._turns: dict[int, ActivityTurn] = {}

    def begin(self, instance_id: int, event_id: int | None, persist: Persist) -> ActivityTurn:
        turn = ActivityTurn(event_id, persist)
        self._turns[instance_id] = turn
        return turn

    def live(self, instance_id: int) -> ActivityTurn | None:
        turn = self._turns.get(instance_id)
        return turn if turn is not None and not turn.done else None
