"""Activity-кадры хода (тикет 012): граф Рана «Лид → Сабагенты» в Playground.

Контракт кадра — ActivityEvent в backend/docs/openapi.yaml (camelCase):
{kind, taskId?, description?, status?, findingsCount?, ts, traceId}. Коллектор — чистое
свёртывание стрим-чанков графа в кадры; фид — live-буфер хода с подписчиками
(SSE runner_api) поверх персиста в hub.activity.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
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


# work log (что агент думает, какие тулы и с чем зовёт, что получил) — превью, не полный текст
WORK_CALL_CHARS = 400
WORK_RESULT_CHARS = 800
WORK_TEXT_CHARS = 2000


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def call_line(name: Any, args: Any) -> str:
    """`grep_code(pattern="jwt", path="src")` — вызов тула одной строкой."""
    if isinstance(args, str):
        with contextlib.suppress(ValueError):
            args = json.loads(args)
    if isinstance(args, dict):
        rendered = ", ".join(
            f"{k}={json.dumps(v, ensure_ascii=False, default=str)}" for k, v in args.items()
        )
    else:
        rendered = "" if args in (None, "", {}) else str(args)
    return _clip(f"{name or 'tool'}({rendered})", WORK_CALL_CHARS)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def message_text(content: Any) -> str:
    """Текст AI-сообщения: строка либо content-блоки провайдера (type=text)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


class ActivityCollector:
    """(mode, serialized chunk) → activity-кадры; держит счётчик Находок Лида
    и статусы Сабагентов (queued до первого прогресс-события)."""

    def __init__(self) -> None:
        self.findings = 0
        self.reply: list[str] = []  # текст AI-сообщений хода — ответ агента в чате
        self._tasks: dict[str, str] = {}  # task_id -> status кадра

    def _frame(self, kind: str, **fields: Any) -> dict[str, Any]:
        return {"kind": kind, "ts": _now(), **{k: v for k, v in fields.items() if v is not None}}

    def run_started(self) -> dict[str, Any]:
        return self._frame("run_started")

    def run_finished(self) -> dict[str, Any]:
        return self._frame("run_finished", findingsCount=self.findings)

    # Транскрипт чата (история как в ChatGPT): реплика пользователя и ответ агента
    # — кадры хода, персистятся в hub.activity, hub отдаёт их GET /instances/{id}/messages.
    def chat_user(self, text: str) -> dict[str, Any]:
        return self._frame("chat_user", text=text)

    def chat_agent(self) -> dict[str, Any] | None:
        text = "\n\n".join(self.reply).strip()
        return self._frame("chat_agent", text=text) if text else None

    def _work(
        self,
        task_id: str | None,
        *,
        text: Any = None,
        calls: list[dict[str, Any]] | None = None,
        result: tuple[Any, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Кадры work log: text (мысль/ответ агента), tool_call (по одному на вызов),
        tool_result (имя тула + превью вывода); taskId — Сабагент, без — Лид."""
        frames: list[dict[str, Any]] = []
        if (
            text := message_text(text).strip()
            if not isinstance(text, str)
            else (text or "").strip()
        ):
            frames.append(
                self._frame("text", taskId=task_id, description=_clip(text, WORK_TEXT_CHARS))
            )
        for call in calls or []:
            frames.append(
                self._frame(
                    "tool_call",
                    taskId=task_id,
                    description=call_line(call.get("name"), call.get("args")),
                )
            )
        if result is not None:
            name, out = result
            frames.append(
                self._frame(
                    "tool_result",
                    taskId=task_id,
                    description=f"{name or 'tool'}: {_clip(str(out or ''), WORK_RESULT_CHARS)}",
                )
            )
        return frames

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
            frames: list[dict[str, Any]] = []
            if self._tasks.get(task_id) == "queued":  # первый шаг: queued → working, один раз
                self._tasks[task_id] = "working"
                frames.append(self._frame("task_started", taskId=task_id, status="working"))
            # шаг Сабагента (core/subagents/steps.py::build_subagent_step) → work log
            if data.get("kind") == "tool":
                frames += self._work(task_id, result=(data.get("tool_name"), data.get("text")))
            elif data.get("kind") == "ai":
                frames += self._work(task_id, text=data.get("text"), calls=data.get("tool_calls"))
            return frames
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
                    if text := message_text(msg.get("content")).strip():
                        self.reply.append(text)
                    frames += self._work(None, text=msg.get("content"), calls=msg.get("tool_calls"))
                elif msg.get("type") == "tool" and msg.get("name") != "task":
                    frames += self._work(None, result=(msg.get("name"), msg.get("content")))
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

    def __init__(self, event_id: int | None, persist: Persist, trace_id: str = "") -> None:
        self.event_id = event_id
        self.trace_id = trace_id
        self.done = False
        self._persist = persist
        self._seq = 0
        self._frames: list[dict[str, Any]] = []
        self._subscribers: list[asyncio.Queue] = []

    async def emit(self, frame: dict[str, Any]) -> None:
        if self.trace_id:
            frame.setdefault("traceId", self.trace_id)
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

    def begin(
        self, instance_id: int, event_id: int | None, persist: Persist, *, trace_id: str = ""
    ) -> ActivityTurn:
        turn = ActivityTurn(event_id, persist, trace_id)
        self._turns[instance_id] = turn
        return turn

    def live(self, instance_id: int) -> ActivityTurn | None:
        turn = self._turns.get(instance_id)
        return turn if turn is not None and not turn.done else None
