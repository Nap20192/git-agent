"""Граф Рана для UI: топология из LangGraph, статусы из run_events.

Топология пайплайна берётся из скомпилированного графа (get_graph) — не
хардкод: добавится узел в build_graph — появится и здесь. Агентный ран
рисуется звездой Лид → Сабагенты по task_*-событиям.
"""

from __future__ import annotations

from functools import cache
from types import SimpleNamespace
from typing import Any

from core.agents.graph import build_graph

_PIPELINE_ORDER = ("scan", "parse", "report")
_HIDDEN = {"__start__", "__end__"}


@cache
def pipeline_topology() -> tuple[list[str], list[dict[str, Any]]]:
    """(узлы, рёбра) из LangGraph API; песочница/модель не нужны для топологии."""
    graph = build_graph(None, None).get_graph()  # type: ignore[arg-type]
    node_ids = [n for n in graph.nodes if n not in _HIDDEN]
    edges = [
        {"from": e.source, "to": e.target, "conditional": bool(e.conditional)}
        for e in graph.edges
        if e.source not in _HIDDEN and e.target not in _HIDDEN
    ]
    return node_ids, edges


def _task_events(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """task_id → свёрнутое состояние делегирования по событиям."""
    tasks: dict[str, dict[str, Any]] = {}
    for event in events:
        data = (event.get("payload") or {}).get("data")
        if not isinstance(data, dict):
            continue
        dtype = data.get("type", "")
        task_id = data.get("task_id")
        if not dtype.startswith("task_") or not task_id:
            continue
        task = tasks.setdefault(task_id, {"taskId": task_id, "status": "running"})
        if dtype == "task_started":
            task.update(
                subagentType=data.get("subagent_type", ""),
                description=data.get("description", ""),
                prompt=data.get("prompt", ""),
            )
        elif dtype != "task_running":
            usage = data.get("usage") or None
            task.update(
                status=dtype.removeprefix("task_"),
                stopReason=data.get("stop_reason"),
                error=data.get("error"),
                usage=usage,
            )
    return tasks


_SUB_TERMINAL_OK = {"completed"}


def _node_status(sub_status: str) -> str:
    if sub_status == "running":
        return "running"
    return "completed" if sub_status in _SUB_TERMINAL_OK else "error"


def _is_agent_run(events: list[dict[str, Any]], node_ids: list[str]) -> bool:
    """Агентный ран: updates-события несут узлы ReAct-цикла, не пайплайна."""
    for event in events:
        if event.get("kind") != "updates":
            continue
        data = (event.get("payload") or {}).get("data")
        if isinstance(data, dict) and any(k not in node_ids for k in data):
            return True
    return False


def _lead_activity(events: list[dict[str, Any]]) -> tuple[int, int]:
    """(число вызовов инструментов Лидом, число report_finding) из updates-событий."""
    tool_calls = findings = 0
    for event in events:
        if event.get("kind") != "updates":
            continue
        data = (event.get("payload") or {}).get("data")
        if not isinstance(data, dict):
            continue
        for value in data.values():
            if not isinstance(value, dict):
                continue
            for msg in value.get("messages") or []:
                if isinstance(msg, dict) and msg.get("type") == "ai":
                    for call in msg.get("tool_calls") or []:
                        tool_calls += 1
                        if call.get("name") == "report_finding":
                            findings += 1
    return tool_calls, findings


def _spread(i: int, n: int, *, center: float = 50.0, step: float = 16.0) -> float:
    """Компактная раскладка i-го из n узлов вокруг center с фиксированным шагом
    (узлы стоят рядом, а не растянуты по всему холсту), с клампом в [8..92]."""
    if n <= 1:
        return center
    y = center + (i - (n - 1) / 2) * step
    return round(max(8.0, min(92.0, y)), 1)


def derive_graph(row: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    run_id = str(row["id"])
    node_ids_probe, _ = pipeline_topology()
    tasks = _task_events(events)
    if tasks or _is_agent_run(events, node_ids_probe):  # агентный ран: звезда Лид → Сабагенты
        lead_status = {
            "succeeded": "completed",
            "failed": "error",
            "interrupted": "error",
        }.get(str(row.get("status")), "running")
        lead_tools, lead_findings = _lead_activity(events)
        # координаты — проценты [0..100] (canvas позиционирует left/top в %):
        # лид слева по центру, Сабагенты веером справа
        nodes: list[dict[str, Any]] = [
            {
                "id": "lead",
                "label": "lead",
                "kind": "agent",
                "status": lead_status,
                "parentId": None,
                "x": 30,
                "y": 50,
                "toolCalls": lead_tools,
                "findings": lead_findings,
            }
        ]
        edges = []
        task_list = list(tasks.values())
        for i, task in enumerate(task_list):
            usage = task.get("usage") or None
            nodes.append(
                {
                    "id": task["taskId"],
                    "label": task.get("description") or task.get("subagentType", "subagent"),
                    "kind": "agent",
                    "status": _node_status(task["status"]),
                    "parentId": "lead",
                    "x": 62,
                    "y": _spread(i, len(task_list)),
                    "subagentType": task.get("subagentType", ""),
                    "description": task.get("description", ""),
                    "subStatus": task["status"],
                    "stopReason": task.get("stopReason"),
                    "tokenUsage": (
                        {
                            "inputTokens": usage.get("input_tokens", 0),
                            "outputTokens": usage.get("output_tokens", 0),
                            "totalTokens": usage.get("total_tokens", 0),
                        }
                        if usage
                        else None
                    ),
                }
            )
            edges.append({"from": "lead", "to": task["taskId"], "conditional": False})
        return {"runId": run_id, "nodes": nodes, "edges": edges}

    # пайплайн: завершённые узлы — по updates-событиям
    node_ids, edges = pipeline_topology()
    completed = set()
    for event in events:
        if event.get("kind") != "updates":
            continue
        data = (event.get("payload") or {}).get("data")
        if isinstance(data, dict):
            completed.update(k for k in data if k in node_ids)
    status = str(row.get("status"))
    error_node = None
    if status in ("failed", "interrupted") and row.get("error"):
        prefix = str(row["error"]).split(":", 1)[0]
        error_node = prefix if prefix in node_ids else None
    nodes = []
    running_marked = False
    for i, node_id in enumerate(sorted(node_ids, key=_PIPELINE_ORDER.index)):
        if node_id in completed:
            node_status = "completed"
        elif node_id == error_node:
            node_status = "error"
        elif status == "running" and not running_marked:
            node_status, running_marked = "running", True
        else:
            node_status = "pending"
        nodes.append(
            {
                "id": node_id,
                "label": node_id,
                "kind": "procedural",
                "status": node_status,
                "parentId": None,
                "x": _spread(i, len(node_ids), center=50, step=22),
                "y": 50,
            }
        )
    return {"runId": run_id, "nodes": nodes, "edges": edges}


@cache
def _sandbox_toolspecs() -> list[dict[str, Any]]:
    """Реальные LangChain-тулы (имена/описания из объектов, не копипаста)."""
    from core.tools.sandbox import build_sandbox_tools

    dummy = SimpleNamespace(repo_dir="/workspace/repo", run=None, close=None)
    return [
        {"name": t.name, "description": (t.description or "").strip()}
        for t in build_sandbox_tools(dummy)  # type: ignore[arg-type]
    ]


def node_spec(
    row: dict[str, Any], node_id: str, events: list[dict[str, Any]]
) -> dict[str, Any] | None:
    from core.agents import nodes as pipeline_nodes
    from core.lead.graph import LEAD_MAX_TURNS, LEAD_SYSTEM_PROMPT
    from core.subagents.registry import BUILTIN_SUBAGENTS

    model = row.get("llm_model")
    base = {
        "id": node_id,
        "label": node_id,
        "kind": "procedural",
        "systemPrompt": None,
        "tools": [],
        "model": model,
        "memoryPreset": None,
    }
    if node_id == "scan":
        return {**base, "description": "Клонирование и обзор структуры репозитория", "model": None}
    if node_id == "parse":
        return {
            **base,
            "description": "Разбор кода: модули, символы, зависимости + LLM-описание",
            "systemPrompt": pipeline_nodes._DESCRIBE_PROMPT.strip(),
        }
    if node_id == "report":
        return {**base, "description": "Сборка итогового структурированного отчёта", "model": None}
    if node_id == "lead":
        return {
            **base,
            "kind": "agent",
            "description": "Лид-агент: исследует репозиторий, делегирует сабагентам",
            "systemPrompt": LEAD_SYSTEM_PROMPT,
            "tools": [
                *_sandbox_toolspecs(),
                {"name": "task", "description": "Делегировать под-исследование сабагенту"},
            ],
            "maxTurns": LEAD_MAX_TURNS,
        }
    task = _task_events(events).get(node_id)
    if task is not None:
        config = BUILTIN_SUBAGENTS.get(task.get("subagentType", ""))
        usage = task.get("usage") or None
        return {
            **base,
            "kind": "agent",
            "label": task.get("description") or node_id,
            "description": config.description if config else "Делегированный сабагент",
            "systemPrompt": config.system_prompt if config else None,
            "tools": _sandbox_toolspecs(),
            "subagentType": task.get("subagentType", ""),
            "delegation": {
                "taskId": node_id,
                "subagentType": task.get("subagentType", ""),
                "description": task.get("description", ""),
                "prompt": task.get("prompt", ""),
                "status": task["status"],
                "stopReason": task.get("stopReason"),
                "error": task.get("error"),
                "acceptanceCriteria": [],
                "tokenUsage": (
                    {
                        "inputTokens": usage.get("input_tokens", 0),
                        "outputTokens": usage.get("output_tokens", 0),
                        "totalTokens": usage.get("total_tokens", 0),
                    }
                    if usage
                    else None
                ),
                "resultBrief": None,
                "toolReceipts": [],
                "receiptVerdict": None,
                "startedAt": None,
                "completedAt": None,
            },
        }
    return None
