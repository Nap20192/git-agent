"""E2E-смоук Раннера: живые Postgres+Rabbit, publish Событие → клейм → фейк-LLM → hub.findings.

Реальные: консьюмер aio-pika, RunnerService, HubInstanceStore, EventExecutor,
лид-граф. Подменены только внешние платные края: LLM (скриптованный tool-call
report_finding) и песочница (фейк). Скипается без Postgres/Rabbit.
"""

from __future__ import annotations

import asyncio
import json
import socket
import uuid

import psycopg
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from core.config import settings
from core.runner.events import Event
from core.runner.executor import EventExecutor
from core.runner.service import RunnerService
from infra.db.hub_store import HubInstanceStore
from infra.hub_client import HttpHubClient


def _pg_available() -> bool:
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2) as conn:
            return bool(
                conn.execute(
                    "SELECT 1 FROM information_schema.tables"
                    " WHERE table_schema = 'hub' AND table_name = 'agent_instances'"
                ).fetchone()
            )
    except Exception:
        return False


def _rabbit_available() -> bool:
    host_port = settings.rabbitmq_url.rsplit("@", 1)[-1].rstrip("/")
    host, _, port = host_port.partition(":")
    try:
        with socket.create_connection((host, int(port or 5672)), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not (_pg_available() and _rabbit_available()), reason="postgres/rabbitmq are not running"
)


class FakeSandbox:
    repo_dir = "/repo"
    id = "e2e-sandbox"

    def __init__(self):
        self.commands: list[str] = []

    async def run(self, command: str, *, timeout_seconds=None) -> str:
        self.commands.append(command)
        return ""

    async def close(self) -> None:
        pass


class ToolFakeModel(GenericFakeChatModel):
    """Фейк с bind_tools (игнорирует биндинг) — как в tests/integration/test_subagents."""

    def bind_tools(self, tools, **kwargs):
        return self


def _seed() -> dict[str, int]:
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE hub.users, hub.identities, hub.llm_connections, hub.sandbox_connections,"
            " hub.agent_builds, hub.repositories, hub.events, hub.sandbox_instances,"
            " hub.runners, hub.agent_instances, hub.instance_events, hub.reports, hub.findings"
            " RESTART IDENTITY CASCADE"
        )
        uid = conn.execute(
            "INSERT INTO hub.users (display_name) VALUES ('e2e') RETURNING id"
        ).fetchone()[0]
        identity = conn.execute(
            "INSERT INTO hub.identities (user_id, provider, provider_user_id, username,"
            " access_token_enc) VALUES (%s, 'github', 'e2e', 'e2e', %s) RETURNING id",
            (uid, b"x"),
        ).fetchone()[0]
        llm = conn.execute(
            "INSERT INTO hub.llm_connections (user_id, name, api_base, api_key_enc, model)"
            " VALUES (%s, 'e2e', 'http://llm', %s, 'fake') RETURNING id",
            (uid, b"x"),
        ).fetchone()[0]
        sconn = conn.execute(
            "INSERT INTO hub.sandbox_connections (name, domain) VALUES ('e2e', 'sb:1') RETURNING id"
        ).fetchone()[0]
        build = conn.execute(
            "INSERT INTO hub.agent_builds (user_id, name, llm_connection_id,"
            " sandbox_connection_id) VALUES (%s, 'e2e', %s, %s) RETURNING id",
            (uid, llm, sconn),
        ).fetchone()[0]
        repo = conn.execute(
            "INSERT INTO hub.repositories (user_id, identity_id, provider, external_id, owner,"
            " name) VALUES (%s, %s, 'github', 'e2e', 'e2e', 'smoke') RETURNING id",
            (uid, identity),
        ).fetchone()[0]
        event = conn.execute(
            "INSERT INTO hub.events (provider, delivery_id, repository_id, action, commit_sha,"
            " payload) VALUES ('github', %s, %s, 'push', 'abc123def456', '{}') RETURNING id",
            (uuid.uuid4().hex, repo),
        ).fetchone()[0]
        instance = conn.execute(
            "INSERT INTO hub.agent_instances (build_id, repository_id, thread_id)"
            " VALUES (%s, %s, 'e2e-thread') RETURNING id",
            (build, repo),
        ).fetchone()[0]
    return {"repo": repo, "event": event, "instance": instance}


def _ai_tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": "c1", "type": "tool_call"}]
    )


def test_event_to_finding_end_to_end(monkeypatch):
    import aio_pika

    import infra.rabbit as rabbit

    queue_name = f"e2e-runners-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(rabbit, "QUEUE", queue_name)

    script = [
        _ai_tool_call(
            "report_finding",
            {
                "title": "E2E: hardcoded secret",
                "severity": "high",
                "description": "смоук-находка",
                "file": "config.py",
                "start_line": 3,
            },
        ),
        AIMessage(content="Разбор завершён: одна находка."),
    ]

    async def main():
        ids = _seed()
        store = HubInstanceStore()
        executor = EventExecutor(
            store=store,
            checkpointer=None,
            connect_sandbox=lambda ctx: _connect(),
            decrypt=lambda enc: "k" if enc is not None else None,
            make_model=lambda **kw: ToolFakeModel(messages=iter(script)),
        )

        async def _connect():
            return FakeSandbox()

        service = RunnerService(
            store=store,
            hub=HttpHubClient(hub_url="", token=""),  # hub выключен — деградация
            executor=executor,
            name=f"e2e-{uuid.uuid4().hex[:6]}",
            address="http://localhost:0",
            slots=1,
            idle_timeout_seconds=60,
        )
        await service.start()
        consumer = asyncio.create_task(
            rabbit.consume_events(settings.rabbitmq_url, service.handle_event)
        )
        try:
            event = Event(
                event_id=ids["event"],
                instance_id=ids["instance"],
                thread_id="e2e-thread",
                repository_id=ids["repo"],
                provider="github",
                action="push",
                dedup_key="abc123def456",
                commit_sha="abc123def456",
            )
            await asyncio.sleep(0.3)  # дать консьюмеру забиндить очередь
            connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            async with connection:
                channel = await connection.channel()
                exchange = await channel.declare_exchange(
                    rabbit.EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
                )
                await exchange.publish(
                    aio_pika.Message(json.dumps(event.to_wire()).encode()),
                    routing_key=f"github.{ids['repo']}.push",
                )
            for _ in range(100):  # ждать processed_at
                with psycopg.connect(settings.database_url) as conn:
                    row = conn.execute(
                        "SELECT processed_at FROM hub.instance_events"
                        " WHERE instance_id = %s AND dedup_key = %s",
                        (ids["instance"], event.dedup_key),
                    ).fetchone()
                if row and row[0] is not None:
                    break
                await asyncio.sleep(0.1)
            else:
                pytest.fail("event was not processed in time")

            with psycopg.connect(settings.database_url) as conn:
                finding = conn.execute(
                    "SELECT severity, file, line_start, evidence FROM hub.findings"
                    " WHERE instance_id = %s",
                    (ids["instance"],),
                ).fetchone()
                instance = conn.execute(
                    "SELECT status, runner_id FROM hub.agent_instances WHERE id = %s",
                    (ids["instance"],),
                ).fetchone()
            assert finding is not None, "finding row must exist"
            assert finding[0] == "high" and finding[1] == "config.py" and finding[2] == 3
            assert "E2E: hardcoded secret" in finding[3]
            assert instance[0] == "running" and instance[1] is not None  # заклеймлен нами

            await channel_cleanup(queue_name)
        finally:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
            await service.shutdown()

    async def channel_cleanup(queue_name: str):
        import aio_pika

        connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            await channel.queue_delete(queue_name)

    asyncio.run(main())
