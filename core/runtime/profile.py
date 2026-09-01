"""GraphProfile — контракт «какой граф исполняет Ран».

Воркер рантайма зависит не от конкретного графа, а от профиля: как собрать
граф, как построить вход из repo_url, как достать отчёт из состояния, какие
stream-режимы и recursion_limit. Дефолт — линейный pipeline (scan→parse→report);
лид-агент подключается своим профилем (core.lead), не трогая воркер.
"""

from __future__ import annotations

import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from core.ports import Sandbox

_CLONE_TIMEOUT_SECONDS = 180.0


async def prepare_repo(sandbox: Sandbox, repo_url: str, checkout_ref: str | None = None) -> None:
    """Клон + опциональный пин коммита; общий prepare для pipeline и лида.

    Работает на КАЖДОЙ попытке (resume = свежая песочница, чекпоинт хранит
    только состояние графа) — без этого resumed-ран продолжается в пустой ФС.
    Полный sha после checkout верифицируется fail-loud: тихий дрейф на дефолтную
    ветку — ровно то, от чего защищается пин.
    """
    repo_dir = shlex.quote(sandbox.repo_dir)
    await sandbox.run(
        f"rm -rf {repo_dir} && git clone --depth 1 {shlex.quote(repo_url)} {repo_dir}",
        timeout_seconds=_CLONE_TIMEOUT_SECONDS,
    )
    if checkout_ref:
        ref = shlex.quote(checkout_ref)
        await sandbox.run(
            f"git -C {repo_dir} fetch --depth 1 origin {ref}"
            f" && git -C {repo_dir} checkout --detach {ref}",
            timeout_seconds=_CLONE_TIMEOUT_SECONDS,
        )
        if len(checkout_ref) == 40:
            head = (await sandbox.run(f"git -C {repo_dir} rev-parse HEAD")).strip()
            if head != checkout_ref:
                raise RuntimeError(f"checkout drift: HEAD {head} != pinned {checkout_ref}")


@dataclass(frozen=True)
class GraphProfile:
    # (sandbox, model, *, checkpointer) -> CompiledStateGraph
    build: Callable[..., Any]
    # (repo_url, checkout_ref|None) -> вход графа (при resume воркер подаёт None)
    make_input: Callable[[str, str | None], Any]
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


def _pipeline_input(repo_url: str, checkout_ref: str | None = None) -> dict[str, Any]:
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
