from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langchain.agents.middleware import (
    AgentMiddleware,
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    SummarizationMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel

from core.memory import MemoryConfig, resolve_memory_preset


@dataclass
class RuntimeFeatures:
    """Declarative feature flags for ``build_agent``."""

    sandbox: bool | AgentMiddleware = False
    # Explicit memory config for direct build_agent(features=...) callers;
    # wins over memory_preset. Otherwise the preset name (or env/production
    # default) is resolved via core.memory.resolve_memory_preset.
    memory_config: MemoryConfig | None = None
    memory_preset: str | None = None
    summarization: Literal[False] | AgentMiddleware = False
    subagent: bool | AgentMiddleware = False
    loop_detection: bool | AgentMiddleware = False
    token_budget: bool | AgentMiddleware = False


_FEATURE_FIELDS = ("sandbox", "subagent", "loop_detection", "token_budget")


def assemble_from_features(
    features: RuntimeFeatures,
    model: BaseChatModel,
    *,
    extra_middleware: list[AgentMiddleware],
) -> list[AgentMiddleware]:
    from core.middleware.tool_result_sanitization import (
        ToolResultSanitizationMiddleware,
    )

    preset = features.memory_config or resolve_memory_preset(features.memory_preset)
    assembled: list[AgentMiddleware] = []
    assembled.append(ToolResultSanitizationMiddleware())
    if isinstance(features.summarization, AgentMiddleware):
        assembled.append(features.summarization)
    elif preset.summarization:
        keep = (
            ("tokens", preset.summarization_keep_tokens)
            if preset.summarization_keep_tokens is not None
            else ("messages", preset.summarization_keep_messages)
        )
        kwargs = {}
        if preset.summary_prompt is not None:
            kwargs["summary_prompt"] = preset.summary_prompt
        assembled.append(
            SummarizationMiddleware(
                model,
                trigger=("tokens", preset.summarization_trigger_tokens),
                keep=keep,
                trim_tokens_to_summarize=preset.summarization_trim_tokens,
                **kwargs,
            )
        )
    if preset.context_editing:
        assembled.append(
            ContextEditingMiddleware(
                edits=[
                    ClearToolUsesEdit(
                        trigger=preset.context_editing_trigger_tokens,
                        keep=preset.context_editing_keep,
                    )
                ]
            )
        )
    for field_name in _FEATURE_FIELDS:
        value = getattr(features, field_name)
        if isinstance(value, AgentMiddleware):
            assembled.append(value)
        elif value is True:
            if field_name == "subagent":
                from core.middleware.subagent_limit import SubagentLimitMiddleware

                assembled.append(SubagentLimitMiddleware())
                continue
            if field_name == "loop_detection":
                from core.middleware.loop_detection import LoopDetectionMiddleware

                assembled.append(LoopDetectionMiddleware())
                continue
            if field_name == "token_budget":
                from core.middleware.token_budget import TokenBudgetMiddleware

                assembled.append(TokenBudgetMiddleware())
                continue
            raise ValueError(
                f"features.{field_name}=True has no built-in middleware; "
                "pass an AgentMiddleware instance or False"
            )
    assembled.extend(extra_middleware)
    from core.middleware.terminal_response import TerminalResponseMiddleware
    from core.middleware.tool_error_handling import ToolErrorHandlingMiddleware

    assembled.append(TerminalResponseMiddleware())
    assembled.append(ToolErrorHandlingMiddleware())
    return assembled
