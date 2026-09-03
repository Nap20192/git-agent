"""Порт-тесты InstanceStore против реального Postgres (схема hub.*, тестовая БД)."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from core.config import settings
from core.runner.crypto import decrypt, encrypt
from core.runner.events import Event
from infra.db.hub_store import HubInstanceStore

KEY = (b"k" * 32).hex()  # SECRETS_KEY — hex (см. core/runner/crypto.py)


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


pytestmark = pytest.mark.skipif(not _pg_available(), reason="postgres/hub schema is not available")


def _conn():
    return psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row)


def _seed() -> dict[str, Any]:
    """Чистый hub.* + полный граф: user→build(llm+sandbox conn)→repo→instance→event."""
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE hub.users, hub.sessions, hub.identities, hub.llm_connections,"
            " hub.sandbox_connections, hub.agent_builds, hub.repositories, hub.events,"
            " hub.outbox, hub.sandbox_instances, hub.runners, hub.agent_instances,"
            " hub.instance_events, hub.reports, hub.findings RESTART IDENTITY CASCADE"
        )
        ids: dict[str, Any] = {}
        row = conn.execute(
            "INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id"
        ).fetchone()
        ids["user"] = row[0]
        ids["identity"] = conn.execute(
            "INSERT INTO hub.identities (user_id, provider, provider_user_id, username,"
            " access_token_enc) VALUES (%s, 'github', 'u1', 'u1', %s) RETURNING id",
            (ids["user"], b"x"),
        ).fetchone()[0]
        ids["llm"] = conn.execute(
            "INSERT INTO hub.llm_connections (user_id, name, api_base, api_key_enc, model)"
            " VALUES (%s, 'llm', 'http://llm', %s, 'gpt-test') RETURNING id",
            (ids["user"], encrypt("llm-key", KEY, nonce=os.urandom(12))),
        ).fetchone()[0]
        ids["sandbox_conn"] = conn.execute(
            "INSERT INTO hub.sandbox_connections (name, domain, api_key_enc, image)"
            " VALUES ('sb', 'sb.local:8090', %s, 'alpine/git') RETURNING id",
            (encrypt("sb-key", KEY, nonce=os.urandom(12)),),
        ).fetchone()[0]
        ids["build"] = conn.execute(
            "INSERT INTO hub.agent_builds (user_id, name, llm_connection_id,"
            " sandbox_connection_id, prompt, limits) VALUES (%s, 'b', %s, %s,"
            " 'только auth', '{\"maxSubagents\": 2}') RETURNING id",
            (ids["user"], ids["llm"], ids["sandbox_conn"]),
        ).fetchone()[0]
        ids["repo"] = conn.execute(
            "INSERT INTO hub.repositories (user_id, identity_id, provider, external_id,"
            " owner, name) VALUES (%s, %s, 'github', 'r1', 'acme', 'shop') RETURNING id",
            (ids["user"], ids["identity"]),
        ).fetchone()[0]
        ids["event"] = conn.execute(
            "INSERT INTO hub.events (provider, delivery_id, repository_id, action,"
            " commit_sha, payload) VALUES ('github', 'd1', %s, 'push', 'abc', '{}')"
            " RETURNING id",
            (ids["repo"],),
        ).fetchone()[0]
        ids["instance"] = conn.execute(
            "INSERT INTO hub.agent_instances (build_id, repository_id, thread_id)"
            " VALUES (%s, %s, 'thread-1') RETURNING id",
            (ids["build"], ids["repo"]),
        ).fetchone()[0]
        return ids


def _event(ids: dict[str, Any], dedup_key: str = "abc") -> Event:
    return Event(
        event_id=ids["event"],
        instance_id=ids["instance"],
        thread_id="thread-1",
        repository_id=ids["repo"],
        provider="github",
        action="push",
        dedup_key=dedup_key,
        commit_sha="abc",
    )


def test_register_runner_upsert():
    async def main():
        _seed()
        store = HubInstanceStore()
        first = await store.register_runner(name="r1", address="http://a", slots=2)
        again = await store.register_runner(name="r1", address="http://b", slots=3)
        assert first == again
        await store.heartbeat_runner(first)

    asyncio.run(main())


def test_claim_release_cas():
    async def main():
        ids = _seed()
        store = HubInstanceStore()
        r1 = await store.register_runner(name="r1", address="http://r1", slots=1)
        r2 = await store.register_runner(name="r2", address="http://r2", slots=1)

        assert (await store.claim_instance(ids["instance"], runner_id=r1)).outcome == "claimed"
        # идемпотентный повторный клейм своим же раннером
        assert (await store.claim_instance(ids["instance"], runner_id=r1)).outcome == "claimed"
        other = await store.claim_instance(ids["instance"], runner_id=r2)
        assert other.outcome == "held_by_other"
        assert other.holder_address == "http://r1"
        # чужой release — no-op, свой — опускает
        assert not await store.release_instance(ids["instance"], runner_id=r2)
        assert await store.release_instance(ids["instance"], runner_id=r1)
        assert (await store.claim_instance(ids["instance"], runner_id=r2)).outcome == "claimed"
        # несуществующий Экземпляр
        assert (await store.claim_instance(999999, runner_id=r1)).outcome == "missing"

    asyncio.run(main())


def test_dedup_journal():
    async def main():
        ids = _seed()
        store = HubInstanceStore()
        event = _event(ids)
        assert await store.begin_event(event)
        # необработанный повтор (ре-публикация) — снова обрабатывать
        assert await store.begin_event(event)
        await store.mark_processed(event.instance_id, event.dedup_key)
        assert not await store.begin_event(event)
        # другой dedup_key — независимая запись
        assert await store.begin_event(_event(ids, dedup_key="def"))

    asyncio.run(main())


def test_load_context_and_decrypt():
    async def main():
        ids = _seed()
        store = HubInstanceStore()
        ctx = await store.load_context(ids["instance"])
        assert ctx["thread_id"] == "thread-1"
        assert ctx["llm_model"] == "gpt-test"
        assert ctx["llm_api_base"] == "http://llm"
        assert decrypt(ctx["llm_api_key_enc"], KEY) == "llm-key"
        assert ctx["sandbox_domain"] == "sb.local:8090"
        assert decrypt(ctx["sandbox_api_key_enc"], KEY) == "sb-key"
        assert (ctx["provider"], ctx["owner"], ctx["name"]) == ("github", "acme", "shop")
        assert ctx["prompt"] == "только auth"
        assert ctx["limits"] == {"maxSubagents": 2}
        assert ctx["sandbox_external_id"] is None
        assert await store.load_context(999999) is None

    asyncio.run(main())


def test_load_context_sees_hub_linked_sandbox():
    """Экземпляр Сэндбокса создаёт hub (по команде юзера); раннер видит его в контексте."""

    async def main():
        ids = _seed()
        with _conn() as conn:
            si = conn.execute(
                "INSERT INTO hub.sandbox_instances (external_id, sandbox_connection_id)"
                " VALUES ('sb-42', %s) RETURNING id",
                (ids["sandbox_conn"],),
            ).fetchone()["id"]
            conn.execute(
                "UPDATE hub.agent_instances SET sandbox_instance_id = %s WHERE id = %s",
                (si, ids["instance"]),
            )
        store = HubInstanceStore()
        ctx = await store.load_context(ids["instance"])
        assert ctx["sandbox_external_id"] == "sb-42"
        assert ctx["sandbox_status"] == "alive"
        with _conn() as conn:
            conn.execute(
                "UPDATE hub.sandbox_instances SET status = 'dead', killed_at = now()"
                " WHERE id = %s",
                (si,),
            )
        assert (await store.load_context(ids["instance"]))["sandbox_status"] == "dead"

    asyncio.run(main())


def test_results_written():
    async def main():
        ids = _seed()
        store = HubInstanceStore()
        report_id = await store.add_report(
            ids["instance"], event_id=ids["event"], summary="итог"
        )
        await store.add_finding(
            ids["instance"],
            {
                "title": "XSS в шаблоне",
                "severity": "medium",
                "description": "вывод без экранирования",
                "file": "tpl.py",
                "startLine": 5,
                "endLine": 6,
                "cwe": "CWE-79",
                "remediation": "экранировать",
            },
        )
        with psycopg.connect(settings.database_url) as conn:
            report = conn.execute(
                "SELECT instance_id, event_id, summary FROM hub.reports WHERE id = %s",
                (report_id,),
            ).fetchone()
            assert report == (ids["instance"], ids["event"], "итог")
            finding = conn.execute(
                "SELECT severity, cwe, file, line_start, line_end, evidence, remediation"
                " FROM hub.findings WHERE instance_id = %s",
                (ids["instance"],),
            ).fetchone()
        assert finding[:5] == ("medium", "CWE-79", "tpl.py", 5, 6)
        assert "XSS в шаблоне" in finding[5] and "без экранирования" in finding[5]
        assert finding[6] == "экранировать"

    asyncio.run(main())
