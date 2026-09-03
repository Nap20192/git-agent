"""HTTP API раннера: подъём/стоп/чат Экземпляров, приём форвардженных Событий, health.

Скоуп служебный: сюда ходят backend (raise/chat-прокси/stop) и соседние раннеры
(форвард). Пользовательского трафика нет — фронт топологию раннеров не знает.
RunnerService кладёт в app.state.service lifespan точки входа (runner.py).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from core.runner import RunnerService, parse_event
from core.runner.activity import message_text
from core.runner.ports import InstanceUnavailableError, SandboxNotProvisionedError
from pkg import trace
from pkg.errors import describe
from pkg.logger import get_logger

log = get_logger(__name__)

api = APIRouter()

_SSE_HEADERS = {"cache-control": "no-cache", "x-accel-buffering": "no"}
_STATUS_CODES = {
    400: "bad_request",
    404: "not_found",
    409: "conflict",
    422: "bad_request",
    503: "unavailable",
}


def _api_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def install_api(app: FastAPI) -> None:
    """Роуты + единый wire-формат ошибок ApiError {"error": {"code", "message"}}
    (как у hub, backend/docs/openapi.yaml): hub проксирует тело как есть."""
    app.include_router(api)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        return _api_error(
            exc.status_code, _STATUS_CODES.get(exc.status_code, "error"), str(exc.detail)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        message = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors()
        )
        return _api_error(422, "bad_request", message)

    @app.exception_handler(InstanceUnavailableError)
    async def _unavailable(_: Request, exc: InstanceUnavailableError) -> JSONResponse:
        return _api_error(409, "instance_unavailable", str(exc))

    @app.exception_handler(SandboxNotProvisionedError)
    async def _no_sandbox(_: Request, exc: SandboxNotProvisionedError) -> JSONResponse:
        return _api_error(424, "sandbox_not_provisioned", str(exc))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception(
            "unhandled error in runner api",
            method=request.method,
            path=request.url.path,
            error=describe(exc),
        )
        return _api_error(500, "internal", f"internal error: {describe(exc)}")


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _failed(frame: dict[str, Any]) -> dict[str, Any]:
    """Кадр-ошибка внутри SSE несёт trace_id запроса: по нему ищутся логи и трейсы."""
    return {**frame, "traceId": trace.current_or_new()}


async def _preflight(service: RunnerService, instance_id: int) -> None:
    """Поднять Экземпляр ДО начала стрима: отказ уходит нормальным HTTP-статусом,
    а не обрывом SSE после 200."""
    if await service.raise_instance(instance_id) == "rejected":
        raise InstanceUnavailableError(instance_id, "held by another runner or missing")


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
async def raise_instance(instance_id: int, request: Request):
    """Быстрый ответ: слот есть — 200 running; слоты заняты — 202 queued
    (подъём продолжается фоном); чужой/незнакомый Экземпляр — 409."""
    status = await _service(request).raise_instance(instance_id)
    if status == "rejected":
        raise HTTPException(409, "instance is held by another runner or missing")
    if status == "queued":
        return JSONResponse({"status": "queued"}, status_code=202)
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
        raise HTTPException(422, describe(exc)) from exc
    if event.instance_id != instance_id:
        raise HTTPException(422, "instanceId mismatch")
    outcome = await _service(request).handle_event(event)
    return {"outcome": outcome}


def chat_events(mode: str, data: Any):
    """(mode, chunk) графа → кадры ChatEvent (контракт backend/docs/openapi.yaml,
    hub проксирует как есть): token — фрагмент ответа по мере генерации (стрим
    `messages` Лида; токены Сабагентов с тегом subagent:* не показываем), message —
    целое AI-сообщение из `updates` (фронт заменяет им накопленные токены: канон и
    фолбэк для провайдеров без стриминга), activity — статусная строка."""
    if mode == "messages":
        if isinstance(data, list) and len(data) == 2 and isinstance(data[0], dict):
            msg, meta = data
            tags = meta.get("tags") if isinstance(meta, dict) else None
            subagent = any(str(t).startswith("subagent:") for t in tags or [])
            is_ai = str(msg.get("type", "")).lower().startswith("ai")
            if is_ai and not subagent and (text := message_text(msg.get("content"))):
                yield {"kind": "token", "text": text}
        return
    if mode == "updates" and isinstance(data, dict):
        for node, update in data.items():
            messages = update.get("messages") if isinstance(update, dict) else None
            for msg in messages or []:
                if not isinstance(msg, dict):
                    continue
                for call in msg.get("tool_calls") or []:
                    yield {"kind": "activity", "text": f"{node}: {call.get('name', 'tool')}"}
                if msg.get("type") == "ai" and (text := message_text(msg.get("content")).strip()):
                    yield {"kind": "message", "text": text}
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
    await _preflight(service, instance_id)

    async def sse():
        try:
            async for mode, data in service.chat(instance_id, message):
                for frame in chat_events(mode, data):
                    yield _sse(frame)
        except Exception as exc:  # заголовки уже ушли: ошибка — кадром, стрим закрывается штатно
            yield _sse(_failed({"kind": "activity", "text": f"error: {describe(exc)}"}))
        yield _sse({"kind": "done"})

    return StreamingResponse(sse(), media_type="text/event-stream", headers=_SSE_HEADERS)


@api.get("/instances/{instance_id}/activity")
async def activity(instance_id: int, request: Request, eventId: int | None = None):
    """Activity-кадры хода (ActivityEvent, openapi.yaml): живой ход — SSE по мере
    появления, завершённый — реплей из hub.activity; терминальный кадр — done.
    Без eventId — живой либо последний ход; eventId — ход этого События."""
    service = _service(request)

    async def sse():
        try:
            async for frame in service.activity(instance_id, event_id=eventId):
                yield _sse(frame)
        except Exception as exc:
            log.exception("activity stream failed", instance_id=instance_id, error=describe(exc))
            yield _sse(_failed({"kind": "run_failed", "description": describe(exc)}))
        yield _sse({"kind": "done"})

    return StreamingResponse(sse(), media_type="text/event-stream", headers=_SSE_HEADERS)


@api.post("/instances/{instance_id}/terminal")
async def terminal(instance_id: int, request: Request):
    """Стрим-консоль (не PTY): {command} → SSE-кадры TerminalEvent
    (output — слитый stdout+stderr, exit — код и новая cwd, done).
    Каждая команда — свежий shell; между командами переносится только cwd."""
    body = await request.json()
    command = (body.get("command") or "").rstrip("\n")
    if not command.strip():
        raise HTTPException(422, "command is required")
    service = _service(request)
    await _preflight(service, instance_id)

    async def sse():
        try:
            output, code, cwd = await service.terminal(instance_id, command)
        except (SandboxNotProvisionedError, InstanceUnavailableError) as exc:
            yield _sse(_failed({"kind": "output", "text": str(exc)}))
            yield _sse({"kind": "exit", "code": None, "cwd": None})
        except Exception as exc:
            log.exception("terminal command failed", instance_id=instance_id, error=describe(exc))
            yield _sse(_failed({"kind": "output", "text": describe(exc)}))
            yield _sse({"kind": "exit", "code": None, "cwd": None})
        else:
            if output:
                yield _sse({"kind": "output", "text": output})
            yield _sse({"kind": "exit", "code": code, "cwd": cwd})
        yield _sse({"kind": "done"})

    return StreamingResponse(sse(), media_type="text/event-stream", headers=_SSE_HEADERS)
