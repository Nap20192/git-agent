"""Санация треда Экземпляра: висящие tool_calls без ToolMessage.

Ход, отменённый (stop / обрыв клиента / краш) после того, как модель эмитнула
tool_calls, но до записи результатов тулов, оставляет в чекпоинте AIMessage с
tool_calls без ответов. Следующий ход добавляет HumanMessage после него, и
провайдер (OpenAI 400 «tool_calls must be followed by tool messages…»)
отвергает историю — тред сломан навсегда. Лечение: дописать за каждый висящий
tool_call_id синтетический ToolMessage. Идемпотентно: чистый тред — ноль записей.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from pkg.logger import get_logger

log = get_logger(__name__)

CANCELLED_TOOL_RESULT = (
    "tool call was cancelled before it produced a result (turn interrupted); do not assume it ran"
)
TOOLS_NODE = "tools"  # имя tools-узла create_agent (langchain 1.x)


def repaired_messages(messages: list[BaseMessage]) -> tuple[list[BaseMessage], int]:
    """(история с дописанными ToolMessage сразу после висящих AIMessage, сколько дописано)."""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    out: list[BaseMessage] = []
    added = 0
    for m in messages:
        out.append(m)
        if not isinstance(m, AIMessage):
            continue
        for call in m.tool_calls:
            if call["id"] in answered:
                continue
            out.append(
                ToolMessage(
                    content=CANCELLED_TOOL_RESULT, tool_call_id=call["id"], name=call["name"]
                )
            )
            added += 1
    return out, added


async def repair_dangling_tool_calls(graph: Any, config: dict[str, Any]) -> int:
    """Починить тред перед ходом (и сразу после отмены хода). Возвращает число дописанных.

    Висящий AIMessage в хвосте — обычный append через add_messages; если после
    него уже есть сообщения (например, HumanMessage упавшего хода) — переписать
    историю целиком (REMOVE_ALL_MESSAGES + порядок), т.к. add_messages в
    середину не вставляет.
    """
    state = await graph.aget_state(config)
    messages = list((state.values or {}).get("messages") or [])
    if not messages:
        return 0
    fixed, added = repaired_messages(messages)
    if not added:
        return 0
    if fixed[: len(messages)] == messages:
        update = fixed[len(messages) :]
    else:
        update = [RemoveMessage(id=REMOVE_ALL_MESSAGES), *fixed]
    await graph.aupdate_state(config, {"messages": update}, as_node=TOOLS_NODE)
    log.warning(
        "thread sanitized: dangling tool_calls answered", repaired=added, rewritten=len(update)
    )
    return added
