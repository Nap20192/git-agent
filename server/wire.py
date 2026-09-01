"""Сериализация в wire-формат контракта (frontend/docs/openapi.yaml).

camelCase на проводе, id — строки. Инвариант redaction: llm_api_key /
connections.api_key никогда не попадают в ответ — только mask_key().
Чистые функции без I/O — тестируются без сервера.
"""

from __future__ import annotations

from typing import Any


def mask_key(key: str | None) -> str:
    if not key:
        return ""
    return f"…{key[-4:]}" if len(key) > 4 else "…"


def repo_slug(url: str) -> str:
    """org/name из URL/пути; хвост .git отрезается."""
    tail = url.rstrip("/").removesuffix(".git")
    parts = [p for p in tail.replace(":", "/").split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else url)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


# ── события ──


def _task_terminal(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    usage = data.get("usage") or None
    return {
        "kind": "task_terminal",
        "taskId": data.get("task_id", ""),
        "subagentType": data.get("subagent_type", ""),
        "status": kind.removeprefix("task_"),
        "stopReason": data.get("stop_reason"),
        "error": data.get("error"),
        "usage": (
            {
                "inputTokens": usage.get("input_tokens", 0),
                "outputTokens": usage.get("output_tokens", 0),
                "totalTokens": usage.get("total_tokens", 0),
            }
            if usage
            else None
        ),
    }


_PIPELINE_NODES = {"scan", "parse", "report"}


def _lead_step_from_messages(node: str, messages: list[Any]) -> dict[str, Any] | None:
    """Развернуть сообщения хода Лида в читаемый agent_step (или None — пусто).

    model-узел несёт AIMessage (рассуждение + tool_calls); tools-узел — ToolMessage
    (результаты). Служебные узлы middleware с пустым value сюда не попадают.
    """
    text_parts: list[str] = []
    tool_calls: list[dict[str, str]] = []
    tool_results: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        mtype = msg.get("type")
        if mtype == "ai":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                text_parts.append(content.strip())
            for call in msg.get("tool_calls") or []:
                tool_calls.append({"name": call.get("name", ""), "args": str(call.get("args", ""))})
        elif mtype == "tool":
            name = msg.get("name", "")
            content = msg.get("content")
            snippet = content if isinstance(content, str) else str(content)
            tool_results.append(f"{name}: {snippet}".strip(": "))
    if not (text_parts or tool_calls or tool_results):
        return None
    return {
        "kind": "agent_step",
        "node": node,
        "text": "\n".join(text_parts),
        "toolCalls": tool_calls,
        "toolResults": tool_results,
    }


def event_to_wire(
    cursor: int, kind: str, payload: dict[str, Any], ts: Any = None
) -> dict[str, Any] | None:
    """run_events-строка / bridge-событие → RunEvent контракта (None = отбросить)."""
    data = payload.get("data") if isinstance(payload, dict) else None
    wire: dict[str, Any] = {"cursor": cursor, "ts": _iso(ts), "type": "custom"}

    if kind == "updates" and isinstance(data, dict):
        node, value = next(iter(data.items()), (None, None))
        if node is None:
            return None
        if node in _PIPELINE_NODES:
            wire.update(
                type="node_update",
                agent=node,
                data={"kind": "node_status", "node": node, "status": "completed"},
            )
            return wire
        # ход агента (Лид): развернуть сообщения; служебные middleware-узлы пусты
        if isinstance(value, dict) and value.get("messages"):
            step = _lead_step_from_messages(node, value["messages"])
            if step is None:
                return None
            wire.update(type="custom", agent="lead", data=step)
            return wire
        return None  # middleware-шум (value None / без messages)

    if isinstance(data, dict) and isinstance(data.get("type"), str):
        dtype = data["type"]
        if dtype == "task_started":
            wire.update(
                type="task_started",
                agent=data.get("task_id"),
                data={
                    "kind": "task_started",
                    "taskId": data.get("task_id", ""),
                    "subagentType": data.get("subagent_type", ""),
                    "description": data.get("description", ""),
                },
            )
            return wire
        if dtype == "task_running":
            calls = data.get("tool_calls") or []
            wire.update(
                type="custom",
                agent=data.get("task_id"),
                data={
                    "kind": "task_step",
                    "taskId": data.get("task_id", ""),
                    "messageIndex": data.get("message_index", 0),
                    "frameKind": data.get("kind", "ai"),
                    "text": data.get("text", ""),
                    "toolName": data.get("tool_name", ""),
                    "toolCalls": [
                        {"name": c.get("name", ""), "args": str(c.get("args", ""))} for c in calls
                    ],
                },
            )
            return wire
        if dtype.startswith("task_"):
            wire.update(type=dtype, agent=data.get("task_id"), data=_task_terminal(dtype, data))
            return wire

    if kind == "usage":
        wire.update(type="custom", data={"kind": "usage", **(payload or {})})
        return wire

    wire.update(type="custom", data=payload)
    return wire


# ── run ──


def _fold_usage(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Суммарный расход по usage-событиям (по одному на попытку)."""
    total: dict[str, int] | None = None
    for event in events:
        if event.get("kind") != "usage":
            continue
        usage = (event.get("payload") or {}).get("usage") or {}
        if total is None:
            total = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
        total["inputTokens"] += usage.get("input_tokens", 0)
        total["outputTokens"] += usage.get("output_tokens", 0)
        total["totalTokens"] += usage.get("total_tokens", 0)
    return total


def run_metrics(row: dict[str, Any], events: list[dict[str, Any]] | None) -> dict[str, Any]:
    started, finished = row.get("started_at"), row.get("finished_at")
    elapsed = 0
    if started is not None:
        from datetime import UTC, datetime

        end = finished or datetime.now(UTC)
        elapsed = max(0, int((end - started).total_seconds()))
    agents_total = agents_active = 0
    usage = None
    if events:
        started_tasks = set()
        finished_tasks = set()
        for event in events:
            data = (event.get("payload") or {}).get("data")
            if not isinstance(data, dict):
                continue
            dtype = data.get("type", "")
            if dtype == "task_started":
                started_tasks.add(data.get("task_id"))
            elif dtype.startswith("task_") and dtype != "task_running":
                finished_tasks.add(data.get("task_id"))
        agents_total = len(started_tasks)
        agents_active = len(started_tasks - finished_tasks) if row.get("status") == "running" else 0
        usage = _fold_usage(events)
    return {
        "agentsActive": agents_active,
        "agentsTotal": agents_total,
        "elapsedSec": elapsed,
        "tokenUsage": usage,
    }


def run_to_wire(row: dict[str, Any], events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    url = row.get("repo_url") or ""
    return {
        "id": str(row["id"]),
        "repositoryId": str(row["repository_id"]),
        "repoUrl": url,
        "repo": repo_slug(url),
        "commitSha": row.get("commit_sha"),
        "status": str(row.get("status")),
        "error": row.get("error"),
        "stopReason": row.get("stop_reason"),
        "cancelRequestedAt": _iso(row.get("cancel_requested_at")),
        "attempt": row.get("attempt", 1),
        "connection": {
            "apiBase": row.get("llm_api_base", ""),
            "model": row.get("llm_model", ""),
            "keyMasked": mask_key(row.get("llm_api_key")),
        },
        "sandbox": row.get("sandbox_name"),
        "limits": row.get("limits"),  # пользовательские лимиты Рана (или null)
        "memoryPreset": None,  # пресет процесса, per-run не хранится
        "hasReport": row.get("report") is not None,
        "createdAt": _iso(row.get("started_at")),
        "startedAt": _iso(row.get("started_at")),
        "finishedAt": _iso(row.get("finished_at")),
        "updatedAt": _iso(row.get("updated_at")) or _iso(row.get("started_at")),
        "metrics": run_metrics(row, events),
    }


def report_to_wire(report: dict[str, Any]) -> dict[str, Any]:
    # агентный Отчёт — финальный ответ Лида: {"answer": ...}
    description = report.get("description", "") or report.get("answer", "")
    structure = report.get("structure") or {}
    wire: dict[str, Any] = {
        "repoUrl": report.get("repo_url", ""),
        "commit": report.get("commit", ""),
        "description": description,
        "structure": {
            "fileCount": structure.get("file_count", 0),
            "totalBytes": structure.get("total_bytes", 0),
            "truncated": structure.get("truncated", False),
            "languages": structure.get("languages", {}),
            "keyFiles": structure.get("key_files", []),
            "files": structure.get("files", []),
        },
        "modules": [
            {
                "path": m.get("path", ""),
                "docstring": m.get("docstring"),
                "classes": m.get("classes", []),
                "functions": m.get("functions", []),
            }
            for m in report.get("modules", [])
        ],
        "dependencies": report.get("dependencies", []),
        "skippedFiles": report.get("skipped_files", []),
    }
    # security-режим: findings уже в camelCase (findings.py::_finding_from_args)
    findings = report.get("findings")
    if findings is not None:
        wire["findings"] = findings
        wire["summary"] = report.get("summary") or description
    if report.get("error"):
        wire["error"] = report["error"]
    return wire


def connection_to_wire(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "apiBase": row["api_base"],
        "model": row["model"],
        "keyMasked": mask_key(row.get("api_key")),
        "createdAt": _iso(row.get("created_at")),
        "lastCheck": row.get("last_check"),
    }


def sandbox_to_wire(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "kind": row["kind"],
        "image": row.get("image"),
        "workdir": row.get("workdir"),
        "createdAt": _iso(row.get("created_at")),
        "runCount": row.get("run_count", 0),
    }
