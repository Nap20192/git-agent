"""Исполнитель делегации: свежий одноразовый граф на каждый запуск.

Изоляция контекста = чистая история ([SystemMessage, HumanMessage]);
checkpointer=False — сабагент никогда не резюмируется. В конфиг ребёнка НЕ
кладутся configurable-ключи (thread_id/checkpoint_ns): явные координаты
чекпоинта протекли бы сообщениями ребёнка в родительский стрим.

Владение терминализацией разделено: путь CancelledError НЕ терминализирует —
собирает урожай (receipts/usage) и перебрасывает, чтобы внешний владелец
(task-тул) корректно проштамповал TIMED_OUT против CANCELLED.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.errors import GraphRecursionError

from core.agents.subagents.contract import SubagentResult, SubagentStatus
from core.agents.subagents.receipts import (
    build_acceptance_criteria_system_note,
    build_report_contract_section,
    extract_citing_turn_receipts,
    extract_tool_receipts,
    render_acceptance_criteria_block,
)
from core.agents.subagents.registry import SubagentConfig
from core.agents.subagents.steps import capture_new_step_messages
from pkg.logger import get_logger

log = get_logger(__name__)


class SubagentTokenCollector(BaseCallbackHandler):
    """Кумулятивный сбор usage: одна запись на run_id, нули не фабрикуются."""

    def __init__(self, caller: str) -> None:
        self._caller = caller
        self._records: list[dict[str, Any]] = []
        self._counted_run_ids: set[str] = set()

    def on_llm_end(self, response: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        key = str(run_id)
        if key in self._counted_run_ids:
            return
        try:
            usage = (response.llm_output or {}).get("token_usage") or {}
            model_name = (response.llm_output or {}).get("model_name")
            if not usage:
                for gens in response.generations:
                    for gen in gens:
                        meta = getattr(gen.message, "usage_metadata", None)
                        if meta:
                            usage = meta
                            break
            input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
            total = int(usage.get("total_tokens") or 0) or input_tokens + output_tokens
            if total <= 0:
                return  # отсутствующий usage не превращается в нули
            self._counted_run_ids.add(key)
            self._records.append(
                {
                    "caller": self._caller,
                    "model_name": model_name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total,
                }
            )
        except Exception:
            log.warning("token usage collection failed", exc_info=True)

    def snapshot_records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def cumulative_usage(self) -> dict[str, int] | None:
        if not self._records:
            return None
        return {
            "input_tokens": sum(r["input_tokens"] for r in self._records),
            "output_tokens": sum(r["output_tokens"] for r in self._records),
            "total_tokens": sum(r["total_tokens"] for r in self._records),
        }


def _build_messages(config: SubagentConfig, task: str, criteria: list[str] | None) -> list[Any]:
    """Ровно ОДИН SystemMessage (строгие провайдеры режут второй) + task."""
    system_parts = [config.system_prompt, build_report_contract_section()]
    human_parts = [task]
    criteria_block = render_acceptance_criteria_block(criteria)
    if criteria_block:
        system_parts.append(build_acceptance_criteria_system_note())
        human_parts.append(criteria_block)
    return [
        SystemMessage(content="\n\n".join(system_parts)),
        HumanMessage(content="\n\n".join(human_parts)),
    ]


def _extract_final_result(final_state: Any) -> str:
    messages = (final_state or {}).get("messages") or []
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            text = message.text
            if text and text.strip():
                return text
            break
    return "No response generated"


class SubagentExecutor:
    def __init__(
        self,
        config: SubagentConfig,
        model: BaseChatModel,
        tools: list[BaseTool],
        *,
        on_step: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.model = model
        self.tools = tools
        self.on_step = on_step

    async def arun(
        self,
        task: str,
        *,
        task_id: str,
        acceptance_criteria: list[str] | None = None,
    ) -> SubagentResult:
        from datetime import UTC, datetime

        from core.agents.factory import build_agent
        from core.agents.middleware.tool_receipts import ToolReceiptMiddleware

        result = SubagentResult(task_id=task_id, status=SubagentStatus.RUNNING)
        result.started_at = datetime.now(UTC)
        collector = SubagentTokenCollector(f"subagent:{self.config.name}")

        # ToolReceiptMiddleware — единственный wrap_tool_call ребёнка (должен
        # быть самым внешним; здесь это выполняется тривиально).
        agent = build_agent(
            self.model,
            self.tools,
            middleware=[ToolReceiptMiddleware()],
            checkpointer=False,  # load-bearing: ребёнок никогда не персистится
            name=f"subagent:{self.config.name}",
        )
        state = {"messages": _build_messages(self.config, task, acceptance_criteria)}
        # НИКАКИХ configurable-ключей (см. докстринг модуля); трейсинг-коллбэки
        # приходят амбиентно из родительской инвокации — не перевешиваем
        # (двойной учёт).
        run_config: dict[str, Any] = {
            "recursion_limit": self.config.max_turns,
            "callbacks": [collector],
            "tags": [f"subagent:{self.config.name}"],
        }

        final_state: Any = None
        captured: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        cursor = 0
        try:
            async for chunk in agent.astream(state, config=run_config, stream_mode="values"):
                final_state = chunk  # удержать ДО любой возможной отмены
                messages = chunk.get("messages") or []
                result.update_tool_receipts([dict(r) for r in extract_tool_receipts(messages)])
                cursor, new_steps = capture_new_step_messages(
                    messages, captured, seen_ids, cursor, task_id=task_id
                )
                if self.on_step:
                    for step in new_steps:
                        self.on_step(step)
                result.update_token_usage_records(collector.snapshot_records())
        except GraphRecursionError:  # раньше generic-обработчика
            partial = _extract_final_result(final_state)
            if partial != "No response generated":
                result.try_set_terminal(
                    SubagentStatus.COMPLETED,
                    result=partial,
                    stop_reason="turn_capped",
                    tool_receipts=self._harvest(final_state),
                    token_usage_records=collector.snapshot_records(),
                )
            else:
                result.try_set_terminal(
                    SubagentStatus.FAILED,
                    error=f"Reached max_turns={self.config.max_turns}",
                    stop_reason="turn_capped",
                    tool_receipts=self._harvest(final_state),
                    token_usage_records=collector.snapshot_records(),
                )
            return result
        except asyncio.CancelledError:
            # урожай — в НЕтерминальный холдер; статус ставит внешний владелец
            result.update_token_usage_records(collector.snapshot_records())
            raise
        except Exception as exc:
            log.exception("subagent failed", subagent=self.config.name, task_id=task_id)
            result.try_set_terminal(
                SubagentStatus.FAILED,
                error=str(exc),
                tool_receipts=self._harvest(final_state),
                token_usage_records=collector.snapshot_records(),
            )
            return result

        result.try_set_terminal(
            SubagentStatus.COMPLETED,
            result=_extract_final_result(final_state),
            tool_receipts=self._harvest(final_state),
            token_usage_records=collector.snapshot_records(),
        )
        return result

    @staticmethod
    def _harvest(final_state: Any) -> list[dict[str, Any]] | None:
        """Снапшот леджера цитирующего хода; fail-closed к None.

        None = урожая нет (вердикта не будет); [] = честный ноль тул-вызовов.
        Перенумерация-склонный рескан хвоста НЕ используется.
        """
        if final_state is None:
            return None
        messages = (final_state or {}).get("messages") or []
        snapshot = extract_citing_turn_receipts(messages)
        if snapshot is not None:
            return [dict(r) for r in snapshot]
        # Снапшота нет (модель ни разу не видела леджер = не было тул-вызовов
        # до последнего хода): пустой леджер — честный ноль.
        if not extract_tool_receipts(messages):
            return []
        return None
