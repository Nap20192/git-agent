"""Per-run бюджет токенов поверх кумулятивной суммы usage_metadata.

Идемпотентность по message id: diff = max(0, current - seen[id]) — повторный
проход того же сообщения и ретроактивные апдейты не считаются дважды.
Hard-stop без исключения: стрип tool_calls + видимая заметка + stop_reason
"token_capped" (аддитивно). Warning — отложенной инъекцией.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

from core.middleware._common import append_hidden_human, strip_all_tool_calls
from pkg.logger import get_logger

log = get_logger(__name__)

STOP_REASON_TOKEN = "token_capped"

_CAP_STOP_NOTE = (
    "\n\n[TOKEN BUDGET REACHED] The token budget for this run is exhausted; further"
    " tool calls were removed. Provide the final answer from what you already have."
)
_WARN_TEMPLATE = (
    "[budget warning] You have used {used:,} of {budget:,} tokens ({pct:.0%})."
    " Wrap up: prioritize synthesizing the final answer over further exploration."
)


class TokenBudgetMiddleware(AgentMiddleware):
    def __init__(self, *, max_total_tokens: int = 1_000_000, warn_fraction: float = 0.8) -> None:
        super().__init__()
        self._budget = max_total_tokens
        self._warn_at = int(max_total_tokens * warn_fraction)
        self._seen: dict[str, int] = {}
        self._total = 0
        self._warned = False
        self._pending_warnings: list[str] = []
        self._stop_reason: str | None = None

    def consume_stop_reason(self) -> str | None:
        reason, self._stop_reason = self._stop_reason, None
        return reason

    @property
    def total_tokens(self) -> int:
        return self._total

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        for message in messages:
            if not isinstance(message, AIMessage) or message.id is None:
                continue
            usage = getattr(message, "usage_metadata", None) or {}
            current = int(usage.get("total_tokens") or 0)
            if current <= 0:
                continue
            diff = max(0, current - self._seen.get(message.id, 0))
            self._seen[message.id] = max(current, self._seen.get(message.id, 0))
            self._total += diff

        log.debug(
            "middleware=token_budget observed",
            total_tokens=self._total,
            budget=self._budget,
        )

        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        last = messages[-1]

        if self._total >= self._budget and last.tool_calls:
            self._stop_reason = STOP_REASON_TOKEN
            log.warning(
                "middleware=token_budget HARD STOP",
                total_tokens=self._total,
                budget=self._budget,
                stripped_calls=len(last.tool_calls),
            )
            return {"messages": [strip_all_tool_calls(last, stop_note=_CAP_STOP_NOTE)]}

        if self._total >= self._warn_at and not self._warned:
            self._warned = True
            self._pending_warnings.append(
                _WARN_TEMPLATE.format(
                    used=self._total, budget=self._budget, pct=self._total / self._budget
                )
            )
            log.warning(
                "middleware=token_budget warn queued",
                total_tokens=self._total,
                budget=self._budget,
            )
        return None

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.after_model(state, runtime)

    def _drain(self, request: Any) -> Any:
        if not self._pending_warnings:
            return request
        warnings, self._pending_warnings = self._pending_warnings, []
        log.info("middleware=token_budget injecting warning")
        return append_hidden_human(request, warnings)

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._drain(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._drain(request))
