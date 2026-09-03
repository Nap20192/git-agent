"""SubagentLimitMiddleware — лид-сторона лимитов делегации."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage

# ре-экспорт для обратной совместимости импортов
from core.middleware._common import (  # noqa: F401
    _TOTAL_LIMIT_STOP_MSG,
    clone_ai_message_with_tool_calls,
)
from core.subagents.contract import SUBAGENT_STATUS_KEY
from pkg.logger import get_logger

log = get_logger(__name__)

DEFAULT_MAX_CONCURRENT = 3
DEFAULT_MAX_TOTAL_PER_RUN = 6


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
