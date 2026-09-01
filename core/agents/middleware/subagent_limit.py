"""SubagentLimitMiddleware — лид-сторона лимитов делегации.

Два лимита, каждый ловит свой сценарий выхода из-под контроля:
- max_concurrent: не больше N task-вызовов в одном ходе модели;
- max_total_per_run: общий бюджет делегаций на запуск — иначе лид обходит
  лимит конкуренции, запуская легальные батчи на каждом чекпойнте.

При исчерпании: task-вызовы вырезаются из ответа модели, finish_reason
форсируется в stop, добавляется видимая заметка — лид синтезирует из
собранного, исключение не бросается.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage

from core.agents.subagents.contract import SUBAGENT_STATUS_KEY
from pkg.logger import get_logger

log = get_logger(__name__)

DEFAULT_MAX_CONCURRENT = 3
DEFAULT_MAX_TOTAL_PER_RUN = 6

_TOTAL_LIMIT_STOP_MSG = (
    "\n\n[SUBAGENT LIMIT REACHED] The delegation budget for this run is exhausted;"
    " further `task` calls were removed. Synthesize the final answer from the"
    " results already collected."
)


def clone_ai_message_with_tool_calls(message: AIMessage, kept_ids: set[str]) -> AIMessage:
    """Клон с отфильтрованными tool_calls; все четыре инварианта гигиены:

    1) фильтруется и provider-raw additional_kwargs["tool_calls"];
    2) function_call выбрасывается, если ничего не осталось;
    3) finish_reason форсируется в stop, когда все вызовы вырезаны;
    4) id сообщения СОХРАНЯЕТСЯ — редьюсер состояния заменяет, а не добавляет.
    """
    kept_calls = [c for c in message.tool_calls if c.get("id") in kept_ids]
    additional_kwargs = dict(message.additional_kwargs or {})
    raw_calls = additional_kwargs.get("tool_calls")
    if isinstance(raw_calls, list):
        filtered = [c for c in raw_calls if isinstance(c, dict) and c.get("id") in kept_ids]
        if filtered:
            additional_kwargs["tool_calls"] = filtered
        else:
            additional_kwargs.pop("tool_calls", None)
    if not kept_calls:
        additional_kwargs.pop("function_call", None)
    response_metadata = dict(message.response_metadata or {})
    if not kept_calls and response_metadata.get("finish_reason") == "tool_calls":
        response_metadata["finish_reason"] = "stop"
    content = message.content
    if not kept_calls and len(kept_ids) < len(message.tool_calls):
        content = (content or "") + _TOTAL_LIMIT_STOP_MSG if isinstance(content, str) else content
    return AIMessage(
        content=content,
        tool_calls=kept_calls,
        additional_kwargs=additional_kwargs,
        response_metadata=response_metadata,
        id=message.id,  # тот же id: замена, не дописывание
    )


class SubagentLimitMiddleware(AgentMiddleware):
    def __init__(
        self,
        *,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        max_total_per_run: int = DEFAULT_MAX_TOTAL_PER_RUN,
    ) -> None:
        super().__init__()
        self.max_concurrent = max_concurrent
        self.max_total_per_run = max_total_per_run

    def _prior_delegations(self, state: Any) -> int:
        # ponytail: счёт по всему треду, консервативен при resume; компакция
        # истории может недосчитать — апгрейд: выделенный счётчик в состоянии.
        return sum(
            1
            for m in state.get("messages", [])
            if isinstance(m, ToolMessage) and SUBAGENT_STATUS_KEY in (m.additional_kwargs or {})
        )

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        last = messages[-1]
        task_calls = [c for c in last.tool_calls if c.get("name") == "task"]
        if not task_calls:
            return None
        allowed = min(
            self.max_concurrent,
            max(0, self.max_total_per_run - self._prior_delegations(state)),
        )
        if len(task_calls) <= allowed:
            return None
        kept_task_ids = {c.get("id") for c in task_calls[:allowed]}
        kept_ids = {
            c.get("id")
            for c in last.tool_calls
            if c.get("name") != "task" or c.get("id") in kept_task_ids
        }
        log.warning(
            "delegation limit applied",
            requested=len(task_calls),
            allowed=allowed,
        )
        return {"messages": [clone_ai_message_with_tool_calls(last, kept_ids)]}

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.after_model(state, runtime)
