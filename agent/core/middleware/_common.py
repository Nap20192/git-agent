"""Общая инфраструктура middleware: клон-гигиена и отложенная инъекция."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

HIDE_FROM_UI_KEY = "hide_from_ui"

_TOTAL_LIMIT_STOP_MSG = (
    "\n\n[SUBAGENT LIMIT REACHED] The delegation budget for this run is exhausted;"
    " further `task` calls were removed. Synthesize the final answer from the"
    " results already collected."
)


def clone_ai_message_with_tool_calls(
    message: AIMessage,
    kept_ids: set[str],
    *,
    stop_note: str | None = None,
) -> AIMessage:
    """Клон с отфильтрованными tool_calls; четыре инварианта гигиены:"""
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
    note = stop_note if stop_note is not None else _TOTAL_LIMIT_STOP_MSG
    if not kept_calls and len(kept_ids) < len(message.tool_calls) and isinstance(content, str):
        content = (content or "") + note
    return AIMessage(
        content=content,
        tool_calls=kept_calls,
        additional_kwargs=additional_kwargs,
        response_metadata=response_metadata,
        id=message.id,
    )


def strip_all_tool_calls(message: AIMessage, *, stop_note: str) -> AIMessage:
    """Hard-stop: вырезать ВСЕ tool_calls + видимая заметка, без исключений."""
    return clone_ai_message_with_tool_calls(message, set(), stop_note=stop_note)


def append_hidden_human(request: Any, texts: list[str]) -> Any:
    """Дописать скрытые HumanMessage в конец request.messages (эфемерно)."""
    if not texts:
        return request
    messages = list(request.messages)
    for text in texts:
        messages.append(HumanMessage(content=text, additional_kwargs={HIDE_FROM_UI_KEY: True}))
    return request.override(messages=messages)
