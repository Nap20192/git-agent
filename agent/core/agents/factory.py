from __future__ import annotations

from typing import Literal

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from core.agents.features import RuntimeFeatures, assemble_from_features


def build_agent(
    model: BaseChatModel,
    tools: list[BaseTool] | None = None,
    *,
    system_prompt: str | None = None,
    middleware: list[AgentMiddleware] | None = None,
    features: RuntimeFeatures | None = None,
    extra_middleware: list[AgentMiddleware] | None = None,
    state_schema: type | None = None,
    checkpointer: BaseCheckpointSaver | Literal[False] | None = None,
    name: str = "default",
) -> CompiledStateGraph:
    if middleware is not None and features is not None:
        raise ValueError("Cannot specify both 'middleware' and 'features'.  Use one or the other.")
    if middleware is not None and extra_middleware:
        raise ValueError("Cannot use 'extra_middleware' with 'middleware' (full takeover).")
    if extra_middleware:
        for mw in extra_middleware:
            if not isinstance(mw, AgentMiddleware):
                raise TypeError(
                    f"extra_middleware items must be AgentMiddleware instances, got {type(mw).__name__}"
                )

    effective_tools: list[BaseTool] = list(tools or [])

    if middleware is not None:
        effective_middleware = list(middleware)
    else:
        effective_middleware = assemble_from_features(
            features or RuntimeFeatures(),
            model,
            extra_middleware=extra_middleware or [],
        )

    return create_agent(
        model=model,
        tools=effective_tools or None,
        middleware=effective_middleware,
        system_prompt=system_prompt,
        state_schema=state_schema,
        checkpointer=checkpointer,
        name=name,
    )
