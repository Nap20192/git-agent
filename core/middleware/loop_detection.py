"""Детектор циклов: P0-гейт от «зовёт один тул с теми же args до recursion_limit».

Два слоя:
1. Идентичные НАБОРЫ tool_calls (порядко-независимый хеш) в скользящем окне.
2. Оконная частота одного тула (много вызовов с разными args).

Hard-stop НЕ бросает исключение: стрипает tool_calls + видимая заметка +
stop_reason (аддитивно). Warning инжектится отложенно — скрытым HumanMessage
в КОНЕЦ следующего model-запроса (вставка в after_model между AIMessage и его
ToolMessage ломает pairing на строгих провайдерах).

Состояние per-instance: у нас граф собирается на один ран (лид) — окно живёт
ровно ран. # ponytail: при переиспользовании инстанса между ранами добавить
ключевание по run_id + BoundedDict.
"""

from __future__ import annotations

import hashlib
from collections import Counter, deque
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

from core.middleware._common import append_hidden_human, strip_all_tool_calls
from pkg.logger import get_logger

log = get_logger(__name__)

STOP_REASON_LOOP = "loop_capped"

_SALIENT_ARG_KEYS = ("command", "path", "url", "query", "pattern", "prompt")

_LOOP_STOP_NOTE = (
    "\n\n[LOOP DETECTED] The same tool calls were repeated too many times; further"
    " tool calls were removed. Provide the final answer from what you already have."
)
_LOOP_WARNING = (
    "[loop warning] You have repeated the same tool call several times with"
    " identical arguments. Change your approach: use different arguments, a"
    " different tool, or synthesize an answer from the results you already have."
)
_FREQ_WARNING = (
    "[loop warning] You are calling the tool '{tool}' very frequently. Step back,"
    " review what you already learned, and change strategy."
)


def _salient(call: dict[str, Any]) -> str:
    args = call.get("args") or {}
    parts = [str(call.get("name") or "")]
    for key in _SALIENT_ARG_KEYS:
        if key in args:
            parts.append(f"{key}={args[key]}")
    if len(parts) == 1:  # нет салиентных ключей — все args
        parts.append(str(sorted(args.items())))
    return ":".join(parts)


def _hash_call_set(calls: list[dict[str, Any]]) -> str:
    canonical = "\n".join(sorted(_salient(c) for c in calls))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class LoopDetectionMiddleware(AgentMiddleware):
    def __init__(
        self,
        *,
        window: int = 20,
        identical_warn: int = 3,
        identical_hard: int = 5,
        tool_freq_warn: int = 30,
        tool_freq_hard: int = 50,
    ) -> None:
        super().__init__()
        self._window = max(window, identical_hard, tool_freq_hard)
        self._identical_warn = identical_warn
        self._identical_hard = identical_hard
        self._freq_warn = tool_freq_warn
        self._freq_hard = tool_freq_hard
        self._history: deque[str] = deque(maxlen=self._window)
        self._tool_history: deque[str] = deque(maxlen=self._window)
        self._warned_hashes: set[str] = set()
        self._warned_tools: set[str] = set()
        self._pending_warnings: list[str] = []
        self._stop_reason: str | None = None

    def consume_stop_reason(self) -> str | None:
        reason, self._stop_reason = self._stop_reason, None
        return reason

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        last = messages[-1]
        if not last.tool_calls:
            return None

        set_hash = _hash_call_set(last.tool_calls)
        self._history.append(set_hash)
        for call in last.tool_calls:
            self._tool_history.append(str(call.get("name") or ""))

        identical_count = sum(1 for h in self._history if h == set_hash)
        tool_counter = Counter(self._tool_history)
        hot_tool, hot_count = tool_counter.most_common(1)[0] if tool_counter else ("", 0)

        log.debug(
            "middleware=loop_detection observed",
            set_hash=set_hash,
            identical_count=identical_count,
            hot_tool=hot_tool,
            hot_count=hot_count,
        )

        if identical_count >= self._identical_hard or hot_count >= self._freq_hard:
            self._stop_reason = STOP_REASON_LOOP
            log.warning(
                "middleware=loop_detection HARD STOP",
                identical_count=identical_count,
                hot_tool=hot_tool,
                hot_count=hot_count,
                stripped_calls=len(last.tool_calls),
            )
            return {"messages": [strip_all_tool_calls(last, stop_note=_LOOP_STOP_NOTE)]}

        if identical_count >= self._identical_warn and set_hash not in self._warned_hashes:
            self._warned_hashes.add(set_hash)
            self._pending_warnings.append(_LOOP_WARNING)
            log.warning(
                "middleware=loop_detection warn queued (identical set)",
                identical_count=identical_count,
                set_hash=set_hash,
            )
        elif hot_count >= self._freq_warn and hot_tool not in self._warned_tools:
            self._warned_tools.add(hot_tool)
            self._pending_warnings.append(_FREQ_WARNING.format(tool=hot_tool))
            log.warning(
                "middleware=loop_detection warn queued (tool frequency)",
                tool=hot_tool,
                count=hot_count,
            )
        return None

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.after_model(state, runtime)

    def _drain(self, request: Any) -> Any:
        if not self._pending_warnings:
            return request
        warnings, self._pending_warnings = self._pending_warnings, []
        log.info("middleware=loop_detection injecting warnings", count=len(warnings))
        return append_hidden_human(request, warnings)

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._drain(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._drain(request))
