"""TurnTracer — читаемый трейс хода в логах: каждый LLM- и тул-вызов с длительностью,
токенами и агентом (lead / subagent:<name>), плюс сводка хода.

Это LangChain-коллбэк: вешается в config["callbacks"] на корневой astream и
наследуется всеми вложенными вызовами (тулы, Сабагенты) через контекст LangChain.
Провайдеры (LangSmith/Langfuse) дают глубокий трейс в UI; этот — «что происходит
прямо сейчас» в консоли и в logs/*.jsonl, с контекстом хода из contextvars.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler

from pkg import trace
from pkg.errors import describe
from pkg.logger import get_logger

log = get_logger(__name__)

_ARGS_PREVIEW_CHARS = 160


@dataclass
class _Span:
    started: float
    agent: str
    tool: str | None = None


@dataclass
class TurnStats:
    """Сводка хода: сколько вызовов, сколько времени и токенов, по агентам и тулам."""

    llm_calls: int = 0
    llm_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: Counter[str] = field(default_factory=Counter)
    tool_ms: Counter[str] = field(default_factory=Counter)
    tool_errors: int = 0
    by_agent: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))

    def as_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "llm_ms": self.llm_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": dict(self.tool_calls),
            "tool_ms": dict(self.tool_ms),
            "tool_errors": self.tool_errors,
            "by_agent": {agent: dict(c) for agent, c in self.by_agent.items()},
        }


def _agent(tags: list[str] | None) -> str:
    for tag in tags or ():
        if tag.startswith("subagent:"):
            return tag
    return "lead"


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _preview(value: Any) -> str:
    text = str(value)
    return text if len(text) <= _ARGS_PREVIEW_CHARS else text[:_ARGS_PREVIEW_CHARS] + "…"


def _usage(response: Any) -> tuple[int, int]:
    """(input, output) токены: usage_metadata сообщения, иначе llm_output.token_usage."""
    try:
        message = response.generations[0][0].message
        usage = getattr(message, "usage_metadata", None) or {}
        if usage:
            return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    except (AttributeError, IndexError):
        pass
    usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
    return (
        int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
    )


def _requested_tools(response: Any) -> list[str]:
    try:
        message = response.generations[0][0].message
    except (AttributeError, IndexError):
        return []
    return [str(c.get("name")) for c in (getattr(message, "tool_calls", None) or [])]


class TurnTracer(AsyncCallbackHandler):
    ignore_chain = True
    ignore_retriever = True

    def __init__(self) -> None:
        super().__init__()
        self._spans: dict[UUID, _Span] = {}
        self.stats = TurnStats()

    # ── LLM ──
    async def on_chat_model_start(
        self,
        serialized: Any,
        messages: Any,
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        **_: Any,
    ) -> None:
        agent = _agent(tags)
        self._spans[run_id] = _Span(time.monotonic(), agent)
        log.debug("llm call started", agent=agent, messages=len(messages[0]) if messages else 0)

    async def on_llm_end(self, response: Any, *, run_id: UUID, **_: Any) -> None:
        span = self._spans.pop(run_id, None)
        if span is None:
            return
        ms = _ms(span.started)
        tokens_in, tokens_out = _usage(response)
        wants = _requested_tools(response)
        self.stats.llm_calls += 1
        self.stats.llm_ms += ms
        self.stats.input_tokens += tokens_in
        self.stats.output_tokens += tokens_out
        self.stats.by_agent[span.agent]["llm_calls"] += 1
        log.info(
            "llm call",
            agent=span.agent,
            duration_ms=ms,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            next=", ".join(wants) if wants else "final answer",
        )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **_: Any) -> None:
        span = self._spans.pop(run_id, None)
        log.warning(
            "llm call failed",
            agent=span.agent if span else "?",
            duration_ms=_ms(span.started) if span else None,
            error=describe(error),
        )

    # ── tools ──
    async def on_tool_start(
        self,
        serialized: Any,
        input_str: str,
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        inputs: dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        name = str((serialized or {}).get("name") or "tool")
        agent = _agent(tags)
        self._spans[run_id] = _Span(time.monotonic(), agent, name)
        log.info(
            "tool call", agent=agent, tool=name, args=_preview(inputs if inputs else input_str)
        )

    async def on_tool_end(self, output: Any, *, run_id: UUID, **_: Any) -> None:
        span = self._spans.pop(run_id, None)
        if span is None or span.tool is None:
            return
        ms = _ms(span.started)
        self.stats.tool_calls[span.tool] += 1
        self.stats.tool_ms[span.tool] += ms
        self.stats.by_agent[span.agent][span.tool] += 1
        content = getattr(output, "content", output)
        log.info(
            "tool done",
            agent=span.agent,
            tool=span.tool,
            duration_ms=ms,
            output_chars=len(str(content)),
        )

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, **_: Any) -> None:
        span = self._spans.pop(run_id, None)
        self.stats.tool_errors += 1
        log.warning(
            "tool failed",
            agent=span.agent if span else "?",
            tool=span.tool if span else "?",
            duration_ms=_ms(span.started) if span else None,
            error=describe(error),
        )

    def summary(self) -> dict[str, Any]:
        """Сводка хода; trace_id — явно, чтобы строка находилась по нему и вне контекста."""
        return {trace.FIELD: trace.current_trace_id(), **self.stats.as_dict()}
