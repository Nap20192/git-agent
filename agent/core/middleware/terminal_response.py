"""Восстановление пустого финального ответа."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import hook_config
from langchain_core.messages import AIMessage, RemoveMessage, ToolMessage

from core.middleware._common import append_hidden_human
from pkg.logger import get_logger

log = get_logger(__name__)

ERROR_FALLBACK_KEY = "error_fallback"

_RECOVERY_PROMPT = (
    "[recovery] Your previous reply was empty. Provide the final answer now,"
    " based on the tool results above."
)
_VISIBLE_ERROR = (
    "The model returned an empty response twice after tool execution."
    " The run ended without a synthesized answer; see the tool results above."
)


def _is_empty_final(message: AIMessage) -> bool:
    if message.tool_calls:
        return False
    text = message.text if isinstance(message.text, str) else ""
    return not (text or "").strip()


class TerminalResponseMiddleware(AgentMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self._retried = False
        self._pending_recovery = False

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        last = messages[-1]
        if not _is_empty_final(last):
            return None
        if not any(isinstance(m, ToolMessage) for m in messages):
            return None

        if not self._retried:
            self._retried = True
            self._pending_recovery = True
            log.warning(
                "middleware=terminal_response empty final; retrying once",
                message_id=last.id,
            )
            return {"messages": [RemoveMessage(id=last.id)], "jump_to": "model"}

        log.error("middleware=terminal_response empty final twice; visible error")
        replacement = AIMessage(
            content=_VISIBLE_ERROR,
            id=last.id,
            additional_kwargs={**(last.additional_kwargs or {}), ERROR_FALLBACK_KEY: True},
        )
        return {"messages": [replacement]}

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.after_model(state, runtime)

    def _drain(self, request: Any) -> Any:
        if not self._pending_recovery:
            return request
        self._pending_recovery = False
        log.info("middleware=terminal_response injecting recovery prompt")
        return append_hidden_human(request, [_RECOVERY_PROMPT])

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._drain(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._drain(request))
