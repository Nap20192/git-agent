"""GraphProfile — контракт «какой граф исполняет Ран».

Воркер рантайма зависит не от конкретного графа, а от профиля: как собрать
граф, как построить вход из repo_url, как достать отчёт из состояния, какие
stream-режимы и recursion_limit. Дефолт — линейный pipeline (scan→parse→report);
лид-агент подключается своим профилем (core.lead), не трогая воркер.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from core.ports import Sandbox
from core.repo import prepare_repo


@dataclass(frozen=True)
class GraphProfile:
    # (sandbox, model, *, checkpointer) -> CompiledStateGraph
    build: Callable[..., Any]
    # (repo_url, checkout_ref|None, instructions|None) -> вход графа (при
    # resume воркер подаёт None; instructions — пользовательская задача Рана)
    make_input: Callable[..., Any]
    # state.values -> отчёт (dict) | None
    extract_report: Callable[[dict[str, Any]], dict[str, Any] | None]
    stream_modes: list[str] = field(default_factory=lambda: ["updates", "custom"])
    run_config: dict[str, Any] = field(default_factory=dict)
    # Подготовка песочницы до графа (clone+checkout). Обязательна для durable-
    # профилей: resume получает свежую пустую песочницу, узлы до чекпоинта
    # (например scan) не перезапускаются.
    prepare: Callable[[Sandbox, str, str | None], Awaitable[None]] | None = None


def _pipeline_build(sandbox: Sandbox, model: BaseChatModel, *, checkpointer: Any = None) -> Any:
    from core.agents.graph import build_graph

    return build_graph(sandbox, model, checkpointer=checkpointer)


def _pipeline_input(
    repo_url: str, checkout_ref: str | None = None, instructions: str | None = None
) -> dict[str, Any]:
    # instructions игнорируются: вход пайплайна фиксирован (scan→parse→report)
    graph_input: dict[str, Any] = {"repo_url": repo_url}
    if checkout_ref:
        graph_input["checkout_ref"] = checkout_ref
    return graph_input


PIPELINE_PROFILE = GraphProfile(
    build=_pipeline_build,
    make_input=_pipeline_input,
    extract_report=lambda values: (values or {}).get("report"),
    prepare=prepare_repo,
)
