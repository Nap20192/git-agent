"""Граф Рана: scan → parse → report (линейный, с управляемыми ошибками).

Песочница и модель передаются снаружи (порт + инстанс), узлы получают их
через замыкания. Ошибка любого узла кладётся в state["error"] и уводит
граф сразу в report.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from core.agents import nodes
from core.agents.state import RepoState
from core.ports import Sandbox
from pkg.logger import get_logger

log = get_logger(__name__)


def _guarded(
    name: str, node: Callable[[RepoState], Awaitable[dict[str, Any]]]
) -> Callable[[RepoState], Awaitable[dict[str, Any]]]:
    async def wrapper(state: RepoState) -> dict[str, Any]:
        try:
            return await node(state)
        except Exception as exc:
            log.exception("node failed", node=name)
            return {"error": f"{name}: {exc}"}

    return wrapper


def _next_or_report(state: RepoState) -> str:
    return "report" if state.get("error") else "next"


def build_graph(
    sandbox: Sandbox, model: BaseChatModel, *, checkpointer: Any | None = None
) -> CompiledStateGraph:
    builder = StateGraph(RepoState)
    builder.add_node("scan", _guarded("scan", lambda s: nodes.scan(s, sandbox)))
    builder.add_node("parse", _guarded("parse", lambda s: nodes.parse(s, sandbox, model)))
    builder.add_node("report", nodes.report)

    builder.add_edge(START, "scan")
    builder.add_conditional_edges("scan", _next_or_report, {"next": "parse", "report": "report"})
    builder.add_edge("parse", "report")
    builder.add_edge("report", END)
    return builder.compile(checkpointer=checkpointer)
