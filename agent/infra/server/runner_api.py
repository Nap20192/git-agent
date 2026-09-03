"""HTTP API раннера: подъём/стоп/чат Экземпляров, приём форвардженных Событий, health.

Скоуп служебный: сюда ходят backend (raise/chat-прокси/stop) и соседние раннеры
(форвард). Пользовательского трафика нет — фронт топологию раннеров не знает.
RunnerService кладёт в app.state.service lifespan точки входа (runner.py).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.runner import RunnerService, parse_event

api = APIRouter()


def _service(request: Request) -> RunnerService:
    service = getattr(request.app.state, "service", None)
    if service is None:
        raise HTTPException(503, "runner is starting")
    return service


@api.get("/health")
async def health(request: Request) -> dict[str, Any]:
    service = _service(request)
    return {"name": service.name, "slots": service.slots, "busy": service.busy}


@api.post("/instances/{instance_id}/raise")
async def raise_instance(instance_id: int, request: Request) -> dict[str, Any]:
    if not await _service(request).raise_instance(instance_id):
        raise HTTPException(409, "instance is held by another runner or missing")
    return {"status": "running"}


@api.post("/instances/{instance_id}/stop")
async def stop_instance(instance_id: int, request: Request) -> dict[str, Any]:
    stopped = await _service(request).stop_instance(instance_id)
    return {"status": "down" if stopped else "not_here"}


@api.post("/instances/{instance_id}/events")
async def accept_event(instance_id: int, request: Request) -> dict[str, Any]:
    try:
        event = parse_event(await request.json())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if event.instance_id != instance_id:
        raise HTTPException(422, "instanceId mismatch")
    outcome = await _service(request).handle_event(event)
    return {"outcome": outcome}


def chat_events(mode: str, data: Any):
    """(mode, chunk) графа → кадры ChatEvent {kind: token|activity, text}
    (контракт backend/docs/openapi.yaml: hub проксирует кадры как есть)."""
    if mode == "updates" and isinstance(data, dict):
        for node, update in data.items():
            messages = update.get("messages") if isinstance(update, dict) else None
            for msg in messages or []:
                if not isinstance(msg, dict):
                    continue
                for call in msg.get("tool_calls") or []:
                    yield {"kind": "activity", "text": f"{node}: {call.get('name', 'tool')}"}
                content = msg.get("content")
                if msg.get("type") == "ai" and not msg.get("tool_calls") and str(content).strip():
                    yield {"kind": "token", "text": str(content)}
        return
    text = data.get("note") if isinstance(data, dict) else None
    yield {
        "kind": "activity",
        "text": str(text) if text else json.dumps(data, ensure_ascii=False, default=str),
    }


@api.post("/instances/{instance_id}/chat")
async def chat(instance_id: int, request: Request):
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(422, "message is required")
    service = _service(request)

    async def sse():
        async for mode, data in service.chat(instance_id, message):
            for frame in chat_events(mode, data):
                yield f"data: {json.dumps(frame, ensure_ascii=False, default=str)}\n\n"
        yield 'data: {"kind": "done"}\n\n'

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
