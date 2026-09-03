"""HTTP API раннера герметично: TestClient + fake-сервис (без lifespan/БД/Rabbit)."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from core.runner.events import Event
from infra.server.runner_api import api

WIRE = {
    "eventId": 7,
    "instanceId": 3,
    "threadId": "inst-3",
    "repositoryId": 5,
    "provider": "github",
    "action": "push",
    "dedupKey": "abc123",
}


class FakeService:
    name = "r1"
    slots = 2

    def __init__(self):
        self.busy = 0
        self.raise_status = "running"
        self.stop_ok = True
        self.events: list[Event] = []
        self.chats: list[tuple[int, str]] = []
        self.terminals: list[tuple[int, str]] = []
        self.terminal_result: tuple[str, int | None, str | None] | Exception = ("ok", 0, "/repo")

    async def raise_instance(self, instance_id: int) -> str:
        return self.raise_status

    async def stop_instance(self, instance_id: int) -> bool:
        return self.stop_ok

    async def handle_event(self, event: Event) -> str:
        self.events.append(event)
        return "processed"

    async def terminal(self, instance_id: int, command: str):
        self.terminals.append((instance_id, command))
        if isinstance(self.terminal_result, Exception):
            raise self.terminal_result
        return self.terminal_result

    async def chat(self, instance_id: int, message: str):
        self.chats.append((instance_id, message))
        yield "custom", {"note": "думаю"}
        yield (
            "updates",
            {
                "lead": {
                    "messages": [
                        {"type": "ai", "content": "", "tool_calls": [{"name": "sandbox_run"}]},
                        {"type": "ai", "content": "готово: всё спокойно"},
                    ]
                }
            },
        )


@pytest.fixture
def service() -> FakeService:
    return FakeService()


@pytest.fixture
def client(service: FakeService) -> TestClient:
    app = FastAPI()
    app.include_router(api)
    app.state.service = service
    return TestClient(app)


def test_health(client, service):
    service.busy = 1
    assert client.get("/health").json() == {"name": "r1", "slots": 2, "busy": 1}


def test_503_before_lifespan():
    app = FastAPI()
    app.include_router(api)
    assert TestClient(app).get("/health").status_code == 503


def test_raise_ok_queued_and_conflict(client, service):
    assert client.post("/instances/3/raise").json() == {"status": "running"}
    service.raise_status = "queued"
    response = client.post("/instances/3/raise")
    assert response.status_code == 202
    assert response.json() == {"status": "queued"}
    service.raise_status = "rejected"
    assert client.post("/instances/3/raise").status_code == 409


def test_stop(client, service):
    assert client.post("/instances/3/stop").json() == {"status": "down"}
    service.stop_ok = False
    assert client.post("/instances/3/stop").json() == {"status": "not_here"}


def test_accept_event(client, service):
    response = client.post("/instances/3/events", json=WIRE)
    assert response.json() == {"outcome": "processed"}
    assert service.events[0].dedup_key == "abc123"


def test_accept_event_mismatch_and_garbage(client, service):
    assert client.post("/instances/9/events", json=WIRE).status_code == 422
    assert client.post("/instances/3/events", json={"eventId": 1}).status_code == 422
    assert service.events == []


def test_chat_sse_stream_is_chat_events(client, service):
    """Кадры — ChatEvent {kind: token|activity|done} (контракт hub openapi)."""
    with client.stream("POST", "/instances/3/chat", json={"message": "что нового?"}) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    frames = [json.loads(line[len("data: "):]) for line in body.splitlines() if line]
    assert [f["kind"] for f in frames] == ["activity", "activity", "token", "done"]
    assert frames[0]["text"] == "думаю"
    assert frames[1]["text"] == "lead: sandbox_run"
    assert frames[2]["text"] == "готово: всё спокойно"
    assert service.chats == [(3, "что нового?")]


def test_chat_requires_message(client, service):
    assert client.post("/instances/3/chat", json={"message": "  "}).status_code == 422
    assert service.chats == []


def _terminal_frames(client, command: str) -> list[dict]:
    with client.stream("POST", "/instances/3/terminal", json={"command": command}) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line]


def test_terminal_sse_frames(client, service):
    """Кадры — TerminalEvent {kind: output|exit|done} (контракт hub openapi)."""
    service.terminal_result = ("total 0\ndrwxr-xr-x", 0, "/repo/sub")
    frames = _terminal_frames(client, "ls -la")
    assert frames == [
        {"kind": "output", "text": "total 0\ndrwxr-xr-x"},
        {"kind": "exit", "code": 0, "cwd": "/repo/sub"},
        {"kind": "done"},
    ]
    assert service.terminals == [(3, "ls -la")]


def test_terminal_empty_output_skips_output_frame(client, service):
    service.terminal_result = ("", 0, "/repo")
    assert [f["kind"] for f in _terminal_frames(client, "true")] == ["exit", "done"]


def test_terminal_unavailable_instance_is_error_frames(client, service):
    service.terminal_result = RuntimeError("instance 3 unavailable: missing")
    frames = _terminal_frames(client, "ls")
    assert frames[0] == {"kind": "output", "text": "instance 3 unavailable: missing"}
    assert frames[1] == {"kind": "exit", "code": None, "cwd": None}
    assert frames[2] == {"kind": "done"}


def test_terminal_requires_command(client, service):
    assert client.post("/instances/3/terminal", json={"command": " \n"}).status_code == 422
    assert service.terminals == []
