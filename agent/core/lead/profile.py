"""GraphProfile — контракт «какой граф исполняет Экземпляр» (раннер зависит от профиля, не от графа)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GraphProfile:
    # (sandbox, model, *, checkpointer) -> CompiledStateGraph
    build: Callable[..., Any]
    # (repo_url, checkout_ref|None, instructions|None) -> вход графа
    make_input: Callable[..., Any]
    # state.values -> отчёт (dict) | None
    extract_report: Callable[[dict[str, Any]], dict[str, Any] | None]
    stream_modes: list[str] = field(default_factory=lambda: ["updates", "custom"])
    run_config: dict[str, Any] = field(default_factory=dict)
