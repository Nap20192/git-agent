"""FastAPI-gateway: тонкий HTTP/SSE-слой над фасадом Runtime."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from infra.server import wire
from infra.server.graphview import derive_graph, node_spec

app: FastAPI  # определяется в конце модуля


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"error": {"code": code, "message": message}})


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from deps import app_deps

    async with app_deps() as deps:
        app.state.runtimes = deps.runtimes
        yield


def create_app(runtime: Any | None = None) -> FastAPI:
    """runtime=None — продакшен (lifespan создаёт свои); в тестах один runtime на оба режима."""
    application = FastAPI(title="git-agent HTTP API", lifespan=None if runtime else _lifespan)
    if runtime is not None:
        application.state.runtimes = {"pipeline": runtime, "agent": runtime}
    _register_routes(application)
    return application


def _runtime(request: Request, mode: str = "pipeline") -> Any:
    runtimes = request.app.state.runtimes
    return runtimes.get(mode) or runtimes["pipeline"]


_LIMIT_KEYS = (
    "subagent",
    "maxSubagents",
    "maxTotalSubagents",
    "tokenBudget",
    "loopDetection",
    "subagentTimeout",
    "queueTimeout",
)


def _limits_from_body(body: dict[str, Any]) -> dict[str, Any] | None:
    """Лимиты Рана из body.features или body.limits (только известные ключи)."""
    src = body.get("limits") or body.get("features")
    if not isinstance(src, dict):
        return None
    limits = {k: src[k] for k in _LIMIT_KEYS if k in src}
    return limits or None


def _lead_tool_calls(events: list[dict[str, Any]]) -> int:
    from infra.server.graphview import _lead_activity

    return _lead_activity(events)[0]


async def _run_mode(request: Request, run_id: int) -> str:
    """Фактический режим Рана — по событиям (агентность видна из updates/task_*)."""
    from infra.server.graphview import _is_agent_run, _task_events, pipeline_topology

    events = await _runtime(request).events(run_id)
    node_ids, _ = pipeline_topology()
    if _task_events(events) or _is_agent_run(events, node_ids):
        return "agent"
    return "pipeline"


async def _run_row_or_404(request: Request, run_id: str) -> dict[str, Any]:
    from infra.db.postgres import get_run_with_repo

    try:
        rid = int(run_id)
    except ValueError as exc:
        raise _error(404, "not_found", f"run {run_id}") from exc
    row = await asyncio.to_thread(get_run_with_repo, rid)
    if row is None:
        raise _error(404, "not_found", f"run {run_id}")
    return row


def _register_routes(application: FastAPI) -> None:
    api = application

    @api.get("/api/runs")
    async def list_runs() -> dict[str, Any]:
        from infra.db.postgres import list_runs_with_repo

        rows = await asyncio.to_thread(list_runs_with_repo)
        return {"runs": [wire.run_to_wire(row) for row in rows]}

    @api.get("/api/runs/{run_id}")
    async def get_run(request: Request, run_id: str) -> dict[str, Any]:
        row = await _run_row_or_404(request, run_id)
        events = await _runtime(request).events(int(run_id))
        return wire.run_to_wire(row, events)

    @api.post("/api/runs")
    async def submit_run(request: Request) -> dict[str, Any]:
        from core.config import settings
        from core.repo import resolve_commit_sha
        from core.runtime.schemas import ConflictError

        body = await request.json()
        repo_url = (body.get("repoUrl") or "").strip()
        if not repo_url:
            raise _error(422, "invalid", "repoUrl is required")

        api_base = body.get("apiBase") or settings.llm_api_base
        api_key = body.get("apiKey") or settings.llm_api_key
        model = body.get("model") or settings.llm_model
        if body.get("connectionId"):
            from infra.db.connections import get_connection

            conn = await asyncio.to_thread(get_connection, int(body["connectionId"]))
            if conn is None:
                raise _error(404, "not_found", f"connection {body['connectionId']}")
            api_base, api_key, model = conn["api_base"], conn["api_key"], conn["model"]

        mode = body.get("mode") or "pipeline"
        if mode not in ("pipeline", "agent"):
            raise _error(422, "invalid", f"unknown mode {mode!r}")
        commit_sha = await resolve_commit_sha(repo_url)
        try:
            result = await _runtime(request, mode).submit(
                repo_url=repo_url,
                commit_sha=commit_sha,
                llm_api_base=api_base,
                llm_api_key=api_key,
                llm_model=model,
                sandbox_name=body.get("sandbox") or "git",
                instructions=body.get("instructions") or None,
                limits=_limits_from_body(body),
            )
        except ConflictError as exc:
            raise _error(409, "conflict", str(exc)) from exc
        row = await _run_row_or_404(request, str(result.run["id"]))
        return {"run": wire.run_to_wire(row), "disposition": result.disposition.value}

    @api.post("/api/runs/{run_id}/cancel")
    async def cancel_run(request: Request, run_id: str) -> dict[str, Any]:
        row = await _run_row_or_404(request, run_id)
        mode = await _run_mode(request, int(run_id))
        await _runtime(request, mode).cancel(int(run_id))
        row = await _run_row_or_404(request, run_id)
        return wire.run_to_wire(row)

    @api.post("/api/runs/{run_id}/resume")
    async def resume_run(request: Request, run_id: str) -> dict[str, Any]:
        row = await _run_row_or_404(request, run_id)
        mode = await _run_mode(request, int(run_id))
        try:
            body = await request.json()
        except Exception:
            body = {}
        new_limits = _limits_from_body(body) if isinstance(body, dict) else None
        result = await _runtime(request, mode).submit(
            repo_url=row["repo_url"],
            commit_sha=row["commit_sha"],
            llm_api_base=row["llm_api_base"],
            llm_api_key=row["llm_api_key"],
            llm_model=row["llm_model"],
            sandbox_name=row.get("sandbox_name") or "git",
            limits=new_limits,
        )
        fresh = await _run_row_or_404(request, run_id)
        return {"run": wire.run_to_wire(fresh), "disposition": result.disposition.value}

    @api.delete("/api/runs/{run_id}", status_code=204)
    async def delete_run(request: Request, run_id: str) -> None:
        from infra.sandbox.instances import kill_run_instances

        await _run_row_or_404(request, run_id)
        # сначала гасим удалённые сэндбоксы Рана (иначе течёт), потом сносим строки
        await kill_run_instances(int(run_id))
        try:
            deleted = await _runtime(request).delete_run(int(run_id))
        except RuntimeError as exc:
            raise _error(409, "conflict", str(exc)) from exc
        if not deleted:
            raise _error(404, "not_found", f"run {run_id}")

    @api.get("/api/runs/{run_id}/report")
    async def get_report(request: Request, run_id: str) -> dict[str, Any]:
        row = await _run_row_or_404(request, run_id)
        if row.get("report") is None:
            raise _error(404, "not_found", f"run {run_id} has no report")
        report = wire.report_to_wire(row["report"])
        if "findings" in report:
            from core.agents.findings import collect_findings_from_events, summarize_findings

            events = await _runtime(request, "agent").events(int(run_id))
            findings = collect_findings_from_events(events)
            report["findings"] = findings
            report["meta"] = {
                **summarize_findings(findings),
                "toolCalls": _lead_tool_calls(events),
                "filesReviewed": len({f["file"] for f in findings if f.get("file")}),
            }
        return report

    @api.get("/api/runs/{run_id}/graph")
    async def get_graph(request: Request, run_id: str) -> dict[str, Any]:
        row = await _run_row_or_404(request, run_id)
        events = await _runtime(request).events(int(run_id))
        return derive_graph(row, events)

    @api.get("/api/runs/{run_id}/nodes/{node_id}")
    async def get_node_spec(request: Request, run_id: str, node_id: str) -> dict[str, Any]:
        row = await _run_row_or_404(request, run_id)
        events = await _runtime(request).events(int(run_id))
        spec = node_spec(row, node_id, events)
        if spec is None:
            raise _error(404, "not_found", f"node {node_id}")
        return spec

    @api.get("/api/runs/{run_id}/events")
    async def stream_events(request: Request, run_id: str, cursor: int | None = None):
        from core.runtime.bridge import END_SENTINEL, HEARTBEAT_SENTINEL, StreamGap

        await _run_row_or_404(request, run_id)
        runtime = _runtime(request)

        def _status_frame(status: Any) -> str:
            payload = {
                "cursor": -1,
                "ts": None,
                "type": "status",
                "data": {"kind": "status", "status": str(status) if status else None},
            }
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        async def sse():
            from core.runtime.schemas import TERMINAL_STATUSES

            row = await runtime.get_run(int(run_id))
            if row is not None and row["status"] in TERMINAL_STATUSES:
                for event in await runtime.events(int(run_id), after_id=cursor):
                    payload = wire.event_to_wire(
                        event["id"],
                        event["kind"],
                        event.get("payload") or {},
                        event.get("created_at"),
                    )
                    if payload is None:
                        continue
                    yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                yield _status_frame(row["status"])
                return
            last_event_id = f"0-{cursor}" if cursor is not None else None
            async for item in runtime.subscribe(int(run_id), last_event_id=last_event_id):
                if item is END_SENTINEL:
                    final = await runtime.get_run(int(run_id))
                    yield _status_frame(final["status"] if final else None)
                    return
                if item is HEARTBEAT_SENTINEL:
                    yield ": heartbeat\n\n"
                    continue
                if isinstance(item, StreamGap):
                    payload = {
                        "cursor": -1,
                        "ts": None,
                        "type": "gap",
                        "data": {
                            "requested": item.requested_event_id,
                            "earliest": item.earliest_available_event_id,
                        },
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    continue
                try:
                    cur = int(str(item.id).rsplit("-", 1)[-1])
                except (TypeError, ValueError):
                    cur = -1
                payload = wire.event_to_wire(cur, item.event, {"data": item.data})
                if payload is None:
                    continue
                yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(
            sse(),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )

    @api.get("/api/runs/{run_id}/chat")
    async def chat_history(request: Request, run_id: str) -> dict[str, Any]:
        await _run_row_or_404(request, run_id)
        turns = await _runtime(request, "agent").chat_history(int(run_id))
        return {"turns": turns}

    @api.post("/api/runs/{run_id}/chat")
    async def chat(request: Request, run_id: str):
        await _run_row_or_404(request, run_id)
        if await _run_mode(request, int(run_id)) != "agent":
            raise _error(422, "not_agent", "chat is available only for agent runs")
        body = await request.json()
        message = (body.get("message") or "").strip()
        if not message:
            raise _error(422, "invalid", "message is required")
        runtime = _runtime(request, "agent")

        async def sse():
            seq = 0
            async for mode, data in runtime.chat(int(run_id), message):
                seq += 1
                payload = wire.event_to_wire(seq, mode, {"data": data})
                if payload is None:
                    continue
                yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            yield 'data: {"type": "chat_done"}\n\n'

        return StreamingResponse(
            sse(),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )

    @api.get("/api/connections")
    async def list_connections() -> dict[str, Any]:
        from infra.db.connections import list_connections as _list

        rows = await asyncio.to_thread(_list)
        return {"connections": [wire.connection_to_wire(r) for r in rows]}

    @api.post("/api/connections")
    async def create_connection(request: Request) -> dict[str, Any]:
        from infra.db.connections import create_connection as _create

        body = await request.json()
        for field in ("name", "apiBase", "apiKey", "model"):
            if not body.get(field):
                raise _error(422, "invalid", f"{field} is required")
        row = await asyncio.to_thread(
            _create, body["name"], body["apiBase"], body["apiKey"], body["model"]
        )
        return wire.connection_to_wire(row)

    @api.delete("/api/connections/{connection_id}", status_code=204)
    async def delete_connection(connection_id: int) -> None:
        from infra.db.connections import delete_connection as _delete

        await asyncio.to_thread(_delete, connection_id)

    @api.post("/api/connections/{connection_id}/check")
    async def check_connection(connection_id: int) -> dict[str, Any]:
        from infra.db.connections import check_connection as _check

        row = await _check(connection_id)
        if row is None:
            raise _error(404, "not_found", f"connection {connection_id}")
        return wire.connection_to_wire(row)

    @api.get("/api/sandboxes")
    async def list_sandboxes() -> dict[str, Any]:
        from infra.db.postgres import list_sandboxes_with_counts

        rows = await asyncio.to_thread(list_sandboxes_with_counts)
        return {"sandboxes": [wire.sandbox_to_wire(r) for r in rows]}

    @api.post("/api/sandboxes")
    async def create_sandbox(request: Request) -> dict[str, Any]:
        from infra.db.postgres import create_sandbox_row

        body = await request.json()
        if not body.get("name") or not body.get("kind"):
            raise _error(422, "invalid", "name and kind are required")
        if body["kind"] == "ssh":
            raise _error(422, "not_implemented", "ssh sandboxes are not implemented")
        row = await asyncio.to_thread(
            create_sandbox_row, body["name"], body["kind"], body.get("image"), body.get("workdir")
        )
        return wire.sandbox_to_wire({**row, "run_count": 0})

    @api.get("/api/sandboxes/instances")
    async def list_sandbox_instances() -> dict[str, Any]:
        from infra.sandbox.instances import list_instances

        rows = await asyncio.to_thread(list_instances)
        return {"instances": [wire.sandbox_instance_to_wire(r) for r in rows]}

    @api.post("/api/sandboxes/instances/{instance_id}/kill")
    async def kill_sandbox_instance(instance_id: int) -> dict[str, Any]:
        from infra.sandbox.instances import kill_sandbox

        row = await kill_sandbox(instance_id)
        if row is None:
            raise _error(404, "not_found", f"sandbox instance {instance_id} not found")
        return wire.sandbox_instance_to_wire(row)

    @api.get("/api/capabilities")
    async def list_capabilities() -> dict[str, Any]:
        from dataclasses import fields

        from core.agents.features import RuntimeFeatures
        from core.subagents.registry import BUILTIN_SUBAGENTS
        from infra.server.graphview import _sandbox_toolspecs

        caps: list[dict[str, Any]] = []
        for config in BUILTIN_SUBAGENTS.values():
            caps.append(
                {
                    "id": f"subagent:{config.name}",
                    "name": config.name,
                    "description": config.description,
                    "source": "subagent",
                    "active": True,
                    "body": config.system_prompt,
                    "usedBy": ["lead"],
                    "tags": ["subagent"],
                }
            )
        for tool in _sandbox_toolspecs():
            caps.append(
                {
                    "id": f"tool:{tool['name']}",
                    "name": tool["name"],
                    "description": tool["description"].split("\n")[0],
                    "source": "tool",
                    "active": True,
                    "body": tool["description"],
                    "usedBy": ["lead", "pipeline", "subagents"],
                    "tags": ["sandbox"],
                }
            )
        for feature in fields(RuntimeFeatures):
            caps.append(
                {
                    "id": f"feature:{feature.name}",
                    "name": feature.name,
                    "description": f"RuntimeFeatures.{feature.name}",
                    "source": "capability",
                    "active": True,
                    "body": "",
                    "usedBy": ["build_agent"],
                    "tags": ["feature-flag"],
                }
            )
        return {"capabilities": caps}

    @api.get("/api/memory-presets")
    async def list_memory_presets() -> dict[str, Any]:
        from core.memory import (
            MEMORY_PRESETS,
            PRODUCTION_FALLBACK_MEMORY_PRESET,
            PRODUCTION_MEMORY_PRESET,
        )

        production = {PRODUCTION_MEMORY_PRESET, PRODUCTION_FALLBACK_MEMORY_PRESET}
        return {
            "presets": [
                {
                    "name": name,
                    "description": getattr(config, "description", "") or name,
                    "production": name in production,
                }
                for name, config in sorted(MEMORY_PRESETS.items())
            ]
        }


app = create_app()
