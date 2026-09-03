"""HttpHubClient герметично (MockTransport): контракт hub'а + деградация warn+retry."""

from __future__ import annotations

import asyncio
import json

import httpx

from core.runner.events import Event
from infra.hub_client import HttpHubClient


def _client(handler) -> HttpHubClient:
    return HttpHubClient(
        hub_url="http://hub", token="s3cret", transport=httpx.MockTransport(handler)
    )


def test_register_and_heartbeat_ok():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("X-Runner-Token")))
        if request.url.path == "/api/runners":
            body = json.loads(request.content)
            assert body == {"name": "r1", "address": "http://r1:8082", "slots": 2}
            return httpx.Response(201, json={"id": 7, "name": "r1"})
        return httpx.Response(204)

    async def run():
        client = _client(handler)
        await client.register(name="r1", address="http://r1:8082", slots=2)
        await client.heartbeat(runner_id=7)
        assert calls == [
            ("POST", "/api/runners", "s3cret"),
            ("POST", "/api/runners/7/heartbeat", "s3cret"),
        ]

    asyncio.run(run())


def test_heartbeat_404_reregisters():
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(404)
        return httpx.Response(201, json={"id": 7})

    async def run():
        client = _client(handler)
        await client.register(name="r1", address="a", slots=1)
        await client.heartbeat(runner_id=7)
        assert paths == ["/api/runners", "/api/runners/7/heartbeat", "/api/runners"]

    asyncio.run(run())


def test_hub_down_degrades_to_warning():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async def run():
        client = _client(handler)
        await client.register(name="r1", address="a", slots=1)  # не бросает
        await client.heartbeat(runner_id=1)  # не бросает
        event = Event(1, 3, "t", 5, "github", "push", "d")
        assert await client.forward_event("http://peer", event) is False

    asyncio.run(run())


def test_disabled_without_hub_url():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("не должно быть запросов к hub")

    async def run():
        client = HttpHubClient(hub_url="", token="", transport=httpx.MockTransport(handler))
        await client.register(name="r1", address="a", slots=1)
        await client.heartbeat(runner_id=1)

    asyncio.run(run())
