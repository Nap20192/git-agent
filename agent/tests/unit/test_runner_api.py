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
        self.raise_ok = True
        self.stop_ok = True
        self.events: list[Event] = []
        self.chats: list[tuple[int, str]] = []

    async def raise_instance(self, instance_id: int) -> bool:
        return self.raise_ok

    async def stop_instance(self, instance_id: int) -> bool:
        return self.stop_ok

    async def handle_event(self, event: Event) -> str:
        self.events.append(event)
        return "processed"

    async def chat(self, instance_id: int, message: str):
        self.chats.append((instance_id, message))
        yield "updates", {"step": 1}
        yield "custom", {"note": "думаю"}


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


def test_raise_ok_and_conflict(client, service):
    assert client.post("/instances/3/raise").json() == {"status": "running"}
    service.raise_ok = False
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


def test_chat_sse_stream(client, service):
    with client.stream("POST", "/instances/3/chat", json={"message": "что нового?"}) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    payloads = [json.loads(line[len("data: "):]) for line in body.splitlines() if line]
    assert [p["type"] for p in payloads] == ["updates", "custom", "chat_done"]
    assert payloads[1]["data"] == {"note": "думаю"}
    assert service.chats == [(3, "что нового?")]


def test_chat_requires_message(client, service):
    assert client.post("/instances/3/chat", json={"message": "  "}).status_code == 422
    assert service.chats == []
