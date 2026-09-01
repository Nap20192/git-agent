"""Тул `task` — единственный вход в систему сабагентов (звезда, глубина 1).

Докстринг тула — политика роутинга: модель читает его при каждом решении
о делегации. Владение терминализацией: TimeoutError → TIMED_OUT,
CancelledError → CANCELLED (и re-raise), исполнитель — COMPLETED/FAILED.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.config import get_stream_writer
from langgraph.types import Command

from core.ports import Sandbox
from core.subagents.capacity import SubagentCapacity, SubagentCapacityError
from core.subagents.contract import (
    SubagentResult,
    SubagentStatus,
    format_subagent_result_message,
    make_subagent_additional_kwargs,
)
from core.subagents.executor import SubagentExecutor
from core.subagents.receipts import render_citation_verdict, verify_receipt_citations
from core.subagents.registry import available_subagent_names, get_subagent_config
from core.tools.sandbox import build_sandbox_tools
from pkg.logger import get_logger

log = get_logger(__name__)


def build_task_tool(
    *,
    sandbox: Sandbox,
    model: BaseChatModel,
    capacity: SubagentCapacity,
    extra_tools: list[BaseTool] | None = None,
) -> BaseTool:
    """Замыкание на песочницу/модель/capacity лида — общих глобалов нет.

    extra_tools — дополнительные тулы Сабагентам поверх sandbox (например
    load_skill в security-режиме); у детей по-прежнему нет тула task.
    """
    child_extra = list(extra_tools or [])

    def _writer():
        try:
            return get_stream_writer()
        except Exception:
            return lambda _payload: None

    @tool("task", parse_docstring=True)
    async def task(
        description: str,
        prompt: str,
        subagent_type: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        acceptance_criteria: list[str] | None = None,
    ) -> Command:
        """Delegate a self-contained task to a subagent with an isolated context.

        Delegate ONLY when the benefit clearly exceeds the overhead: (1) parallel
        independent work, (2) heavy research whose intermediate context you do not
        need — the subagent burns its own context and returns only a report, or
        (3) a specialized subagent type fits better. Do NOT delegate merely
        because a task is complex or multi-step. Do NOT split dependent steps
        into parallel subagents. Do NOT run parallel subagents over overlapping
        mutable state. Each delegation costs a full agent run; a subagent's
        report is a SELF-REPORT — spot-check its verifiable handles yourself.

        Args:
            description: FIRST - short 3-5 word label for progress display.
            prompt: SECOND - the full task assignment; the subagent sees nothing
                else, so include all needed context and the expected output.
            subagent_type: THIRD - subagent type name; see available types in
                the error message if unsure.
            acceptance_criteria: optional list of verifiable completion criteria.
        """
        writer = _writer()
        config = get_subagent_config(subagent_type)
        if config is None:
            content = (
                f"Unknown subagent type '{subagent_type}'."
                f" Available: {', '.join(available_subagent_names())}"
            )
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=f"Task Failed. {content}",
                            name="task",
                            tool_call_id=tool_call_id,
                            additional_kwargs=make_subagent_additional_kwargs(
                                SubagentStatus.FAILED, error=content
                            ),
                        )
                    ]
                }
            )

        writer(
            {
                "type": "task_started",
                "task_id": tool_call_id,
                "description": description,
                "subagent_type": subagent_type,
            }
        )

        def on_step(step: dict[str, Any]) -> None:
            writer({"type": "task_running", **step})

        executor = SubagentExecutor(
            config, model, [*build_sandbox_tools(sandbox), *child_extra], on_step=on_step
        )
        result = SubagentResult(task_id=tool_call_id)
        try:
            async with capacity.slot():
                result = await asyncio.wait_for(
                    executor.arun(
                        prompt,
                        task_id=tool_call_id,
                        acceptance_criteria=acceptance_criteria,
                    ),
                    timeout=config.timeout_seconds,
                )
        except SubagentCapacityError as exc:
            result.try_set_terminal(SubagentStatus.FAILED, error=f"Delegation not admitted: {exc}")
        except TimeoutError:
            result.try_set_terminal(
                SubagentStatus.TIMED_OUT,
                error=f"Execution timed out after {config.timeout_seconds:g}s",
            )
        except asyncio.CancelledError:
            result.try_set_terminal(SubagentStatus.CANCELLED, error="Cancelled")
            writer(_terminal_event(result, subagent_type, executor=None))
            raise  # re-raise обязателен

        verdict = None
        if (
            result.status is SubagentStatus.COMPLETED
            and result.tool_receipts is not None
            and result.result
        ):
            # единственное место с неусечённым отчётом; [] — честный ноль
            # вызовов и тоже вердикт-годен, None пропускает вердикт
            verdict = verify_receipt_citations(result.result, result.tool_receipts)

        usage = _cumulative_usage(result)
        writer(_terminal_event(result, subagent_type, usage=usage))

        content = format_subagent_result_message(
            result.status,
            result=result.result,
            error=result.error,
            stop_reason=result.stop_reason,
        )
        if verdict is not None:
            verdict_line = render_citation_verdict(verdict)
            if verdict_line:
                content += f"\n\n[{verdict_line}]"
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=content,
                        name="task",
                        tool_call_id=tool_call_id,
                        additional_kwargs=make_subagent_additional_kwargs(
                            result.status,
                            result=result.result,
                            error=result.error,
                            stop_reason=result.stop_reason,
                            token_usage=usage,
                            tool_receipts=result.tool_receipts,
                            receipt_verdict=verdict,
                        ),
                    )
                ]
            }
        )

    return task


def _cumulative_usage(result: SubagentResult) -> dict[str, int] | None:
    if not result.token_usage_records:
        return None
    return {
        "input_tokens": sum(r.get("input_tokens", 0) for r in result.token_usage_records),
        "output_tokens": sum(r.get("output_tokens", 0) for r in result.token_usage_records),
        "total_tokens": sum(r.get("total_tokens", 0) for r in result.token_usage_records),
    }


def _terminal_event(
    result: SubagentResult,
    subagent_type: str,
    *,
    usage: dict[str, int] | None = None,
    executor: Any = None,
) -> dict[str, Any]:
    return {
        "type": f"task_{result.status.value}",
        "task_id": result.task_id,
        "subagent_type": subagent_type,
        "stop_reason": result.stop_reason,
        "error": result.error,
        # usage кумулятивный, replace-семантика для потребителей (не суммируйте
        # с прогресс-кадрами)
        "usage": usage,
    }
