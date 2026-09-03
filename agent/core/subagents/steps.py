"""Захват шагов сабагента из values-стрима (чистые функции)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

SUBAGENT_STEP_MAX_CHARS = 8192
_ARGS_PREVIEW_MAX_CHARS = 2000


def truncate_step_text(text: str, max_chars: int = SUBAGENT_STEP_MAX_CHARS) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, default=str)
    except Exception:
        return str(content)


def build_subagent_step(
    message: BaseMessage, *, task_id: str, message_index: int
) -> dict[str, Any]:
    text, truncated = truncate_step_text(_content_to_text(message.content or ""))
    step: dict[str, Any] = {
        "task_id": task_id,
        "message_index": message_index,
        "kind": "ai" if isinstance(message, AIMessage) else "tool",
        "text": text,
        "truncated": truncated,
    }
    if isinstance(message, AIMessage) and message.tool_calls:
        calls = []
        for call in message.tool_calls:
            args_preview = json.dumps(call.get("args") or {}, ensure_ascii=False, default=str)
            args_truncated = len(args_preview) > _ARGS_PREVIEW_MAX_CHARS
            calls.append(
                {
                    "name": call.get("name"),
                    "args": args_preview[:_ARGS_PREVIEW_MAX_CHARS],
                    "args_truncated": args_truncated,
                }
            )
        step["tool_calls"] = calls
    if isinstance(message, ToolMessage):
        step["tool_name"] = message.name
    return step


def _capture(
    message: BaseMessage, captured: list[dict], seen_ids: set[str], *, task_id: str, index: int
) -> bool:
    if not isinstance(message, (AIMessage, ToolMessage)):
        return False
    if message.id is not None:
        if message.id in seen_ids:
            return False
        seen_ids.add(message.id)
    else:
        step = build_subagent_step(message, task_id=task_id, message_index=index)
        if any(c == step for c in captured):
            return False
        captured.append(step)
        return True
    captured.append(build_subagent_step(message, task_id=task_id, message_index=index))
    return True


def capture_new_step_messages(
    messages: list[BaseMessage],
    captured: list[dict],
    seen_ids: set[str],
    processed_count: int,
    *,
    task_id: str,
) -> tuple[int, list[dict]]:
    """Обработать новый хвост; вернуть (новый курсор, новые шаги)."""
    total = len(messages)
    new_steps: list[dict] = []
    before = len(captured)
    if total < processed_count:
        processed_count = 0
    if total > processed_count:
        for index in range(processed_count, total):
            _capture(messages[index], captured, seen_ids, task_id=task_id, index=index)
    elif total and total == processed_count:
        _capture(messages[-1], captured, seen_ids, task_id=task_id, index=total - 1)
    new_steps = captured[before:]
    return total, new_steps
