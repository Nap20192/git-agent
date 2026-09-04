"""Санация треда Экземпляра: висящие tool_calls без ToolMessage и обрезанные tool_calls.

Ход, отменённый (stop / обрыв клиента / краш) после того, как модель эмитнула
tool_calls, но до записи результатов тулов, оставляет в чекпоинте AIMessage с
tool_calls без ответов. Следующий ход добавляет HumanMessage после него, и
провайдер (OpenAI 400 «tool_calls must be followed by tool messages…»)
отвергает историю — тред сломан навсегда. Лечение: дописать за каждый висящий
tool_call_id синтетический ToolMessage. Идемпотентно: чистый тред — ноль записей.

Второй случай — `invalid_tool_calls`: генерация упёрлась в лимит вывода (n_predict /
max_tokens), JSON аргументов обрезан. langchain_openai шлёт такие вызовы провайдеру
как есть, и llama.cpp отвечает 500 «Failed to parse tool call arguments as JSON» уже
на ВХОДЕ — каждый следующий ход падает за секунды. Лечение: выкинуть invalid_tool_calls
из AIMessage, оставив в тексте пометку, что вызов был обрезан.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from core.runner.activity import message_text
from pkg.logger import get_logger

log = get_logger(__name__)

CANCELLED_TOOL_RESULT = (
    "tool call was cancelled before it produced a result (turn interrupted); do not assume it ran"
)
TRUNCATED_TOOL_CALL_NOTE = (
    "[a tool call was truncated by the output token limit and dropped; "
    "re-issue it in a shorter form]"
)
TOOLS_NODE = "tools"  # имя tools-узла create_agent (langchain 1.x)


def repaired_messages(messages: list[BaseMessage]) -> tuple[list[BaseMessage], int]:
    """(история с дописанными ToolMessage сразу после висящих AIMessage, сколько дописано)."""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    out: list[BaseMessage] = []
    added = 0
    for m in messages:
        if isinstance(m, AIMessage) and m.invalid_tool_calls:
            text = m.content if isinstance(m.content, str) else message_text(m.content)
            m = m.model_copy(
                update={
                    "content": "\n\n".join(
                        x for x in (text.strip(), TRUNCATED_TOOL_CALL_NOTE) if x
                    ),
                    "invalid_tool_calls": [],
                }
            )
            added += 1
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
        "thread sanitized: dangling/truncated tool_calls repaired",
        repaired=added,
        rewritten=len(update),
    )
    return added
