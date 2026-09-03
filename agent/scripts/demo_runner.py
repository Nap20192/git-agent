"""Интерактивное демо Раннера вживую: `uv run python scripts/demo_runner.py`.

Реальные RabbitMQ (5673) и Postgres (hub.*), реальные консьюмер/сервис/store —
только исполнение подменено DemoExecutor'ом (без LLM и песочницы): он печатает
шаги и пишет демо-Находку/Отчёт в hub через тот же порт. Видно весь путь
События: publish → очередь → клейм CAS → дедуп → «исполнение» → processed_at,
плюс слоты, idle-выгрузку, форвард держателю и чат. HTTP API поднимается на
RUNNER_PORT — можно параллельно curl'ить /health и /instances/{id}/chat.

Демо-строки в БД намespace'ены 'demo-'; команда clean сносит их.
"""

import asyncio
import contextlib
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # корень проекта в path

import aio_pika
import psycopg
from psycopg.rows import dict_row

from core.config import settings
from core.runner.events import Event
from core.runner.executor import repo_url
from core.runner.service import RunnerService
from infra.db.hub_store import HubInstanceStore
from infra.rabbit import EXCHANGE, consume_events

SLOTS = 1  # один слот — контеншн виден невооружённым глазом
IDLE_SECONDS = 45.0
DEAD_RUNNER_ADDRESS = "http://localhost:9999"  # держатель B недоступен — виден warn форварда

HELP = """\
Команды:
  send [a|c]   — опубликовать новое Событие для Экземпляра A или C (дефолт a)
  dup          — повторить последнее Событие (демо дедупа по dedup_key)
  fwd          — Событие для Экземпляра B (running у «мёртвого» раннера → форвард → warn)
  status       — слоты, Экземпляры, журнал Событий, Отчёты/Находки из БД
  chat <текст> — чат с Экземпляром A (SSE-поток в консоль)
  stop a|c     — опустить Экземпляр (running→down, слот свободен)
  reap         — форсировать idle-проход (авто-цикл тоже работает, таймаут 45с)
  clean        — снести demo-строки из hub.* и выйти
  q            — выход (graceful: Экземпляры опускаются)
"""


def _p(line: str) -> None:
    print(line, flush=True)


class DemoExecutor:
    """Вместо LLM+песочницы: печатает шаги и пишет результат через реальный store."""

    def __init__(self, store: HubInstanceStore) -> None:
        self._store = store

    async def process_event(self, ctx: dict, event: Event) -> None:
        _p(
            f"  🤖 [exec] поднимаю агента из Сборки: model={ctx['llm_model']},"
            f" sandbox={ctx['sandbox_domain']} ({ctx['sandbox_image']})"
        )
        await asyncio.sleep(1.0)
        _p(
            f"  📥 [exec] клонирую {repo_url(ctx)} @ {event.commit_sha or 'HEAD'}"
            f" (thread_id={ctx['thread_id']} копит знание между Событиями)"
        )
        await asyncio.sleep(1.5)
        _p("  🔎 [exec] «лид делегирует проверки Сабагентам…»")
        await asyncio.sleep(1.5)
        await self._store.add_finding(
            ctx["id"],
            {
                "title": f"Демо-находка по {event.action} {event.commit_sha or ''}".strip(),
                "severity": "medium",
                "description": "сымитировано DemoExecutor'ом",
                "file": "app/demo.py",
                "startLine": 1,
                "endLine": 2,
                "cwe": "CWE-000",
                "remediation": "ничего — это демо",
            },
        )
        report_id = await self._store.add_report(
            ctx["id"],
            event_id=event.event_id,
            summary=f"Демо-отчёт: разобрано Событие {event.action} ({event.dedup_key}).",
        )
        _p(f"  ✅ [exec] report_finding + write_report записаны (report id={report_id})")

    async def chat_stream(self, ctx: dict, message: str):
        yield "custom", {"note": f"думаю над «{message}»…"}
        await asyncio.sleep(0.8)
        yield (
            "updates",
            {
                "lead": {
                    "messages": [
                        {
                            "type": "ai",
                            "content": f"Демо-ответ: по треду {ctx['thread_id']} всё спокойно.",
                        }
                    ]
                }
            },
        )


def _conn() -> psycopg.Connection:
    return psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row)


def seed_demo() -> dict[str, int]:
    """Идемпотентный сид: Сборка + три Репозитория/Экземпляра (A, C наши; B — у мёртвого)."""
    with _conn() as conn:
        user = (
            conn.execute("SELECT id FROM hub.users WHERE display_name = 'demo'").fetchone()
            or conn.execute(
                "INSERT INTO hub.users (display_name) VALUES ('demo') RETURNING id"
            ).fetchone()
        )
        uid = user["id"]
        identity = conn.execute(
            "INSERT INTO hub.identities (user_id, provider, provider_user_id, username,"
            " access_token_enc) VALUES (%s, 'github', 'demo', 'demo', %s)"
            " ON CONFLICT (provider, provider_user_id) DO UPDATE SET username = 'demo'"
            " RETURNING id",
            (uid, b"demo"),
        ).fetchone()
        llm = (
            conn.execute(
                "SELECT id FROM hub.llm_connections WHERE user_id = %s AND name = 'demo-llm'",
                (uid,),
            ).fetchone()
            or conn.execute(
                "INSERT INTO hub.llm_connections (user_id, name, api_base, api_key_enc, model)"
                " VALUES (%s, 'demo-llm', 'http://llm.demo', %s, 'demo-model') RETURNING id",
                (uid, b"demo"),
            ).fetchone()
        )
        sandbox = conn.execute(
            "INSERT INTO hub.sandbox_connections (name, domain, image)"
            " VALUES ('demo-sandbox', 'sandbox.demo:8090', 'alpine/git')"
            " ON CONFLICT (name) DO UPDATE SET domain = EXCLUDED.domain RETURNING id"
        ).fetchone()
        build = conn.execute(
            "INSERT INTO hub.agent_builds (user_id, name, llm_connection_id,"
            " sandbox_connection_id, prompt) VALUES (%s, 'demo-build', %s, %s,"
            " 'демо: смотри только на auth') ON CONFLICT (user_id, name)"
            " DO UPDATE SET prompt = EXCLUDED.prompt RETURNING id",
            (uid, llm["id"], sandbox["id"]),
        ).fetchone()
        dead_runner = conn.execute(
            "INSERT INTO hub.runners (name, address, slots) VALUES ('demo-runner-dead', %s, 1)"
            " ON CONFLICT (name) DO UPDATE SET address = EXCLUDED.address RETURNING id",
            (DEAD_RUNNER_ADDRESS,),
        ).fetchone()

        ids: dict[str, int] = {}
        for key, repo_name in (("a", "alpha"), ("b", "bravo"), ("c", "charlie")):
            repo = conn.execute(
                "INSERT INTO hub.repositories (user_id, identity_id, provider, external_id,"
                " owner, name) VALUES (%s, %s, 'github', %s, 'demo', %s)"
                " ON CONFLICT (user_id, provider, external_id) DO UPDATE SET name = EXCLUDED.name"
                " RETURNING id",
                (uid, identity["id"], f"demo-{repo_name}", repo_name),
            ).fetchone()
            instance = conn.execute(
                "INSERT INTO hub.agent_instances (build_id, repository_id, thread_id)"
                " VALUES (%s, %s, %s) ON CONFLICT (build_id, repository_id)"
                " DO UPDATE SET updated_at = now() RETURNING id",
                (build["id"], repo["id"], f"demo-{repo_name}"),
            ).fetchone()
            ids[key] = instance["id"]
            ids[f"repo_{key}"] = repo["id"]
        # A и C — чистый старт (прошлое демо могло быть убито без graceful shutdown)
        conn.execute(
            "UPDATE hub.agent_instances SET status = 'down', runner_id = NULL"
            " WHERE id = ANY(%s)",
            ([ids["a"], ids["c"]],),
        )
        # B «running» у мёртвого держателя — для демо форварда
        conn.execute(
            "UPDATE hub.agent_instances SET status = 'running', runner_id = %s WHERE id = %s",
            (dead_runner["id"], ids["b"]),
        )
    return ids


def clean_demo() -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM hub.users WHERE display_name = 'demo'")  # каскадом всё demo-
        conn.execute("DELETE FROM hub.runners WHERE name LIKE 'demo-%'")
    _p("🧹 demo-строки удалены")


async def publish_event(ids: dict[str, int], key: str, *, dedup: str | None = None) -> Event:
    """Как это делает hub: строка в hub.events + publish в exchange events."""
    commit = dedup or uuid.uuid4().hex[:12]
    with _conn() as conn:
        row = conn.execute(
            "INSERT INTO hub.events (provider, delivery_id, repository_id, action, commit_sha,"
            " payload) VALUES ('github', %s, %s, 'push', %s, '{}') RETURNING id",
            (uuid.uuid4().hex, ids[f"repo_{key}"], commit),
        ).fetchone()
    event = Event(
        event_id=row["id"],
        instance_id=ids[key],
        thread_id=f"demo-{key}",
        repository_id=ids[f"repo_{key}"],
        provider="github",
        action="push",
        dedup_key=commit,
        commit_sha=commit,
    )
    connection = await aio_pika.connect_robust(settings.rabbit_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )
        await exchange.publish(
            aio_pika.Message(
                json.dumps(event.to_wire()).encode(), delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key=f"github.{event.repository_id}.push",
        )
    _p(f"📨 Событие опубликовано: instance={event.instance_id} dedup_key={event.dedup_key}")
    return event


def show_status(service: RunnerService, ids: dict[str, int]) -> None:
    _p(f"🎛  раннер {service.name}: слотов {service.slots}, занято {service.busy}")
    with _conn() as conn:
        rows = conn.execute(
            "SELECT i.id, i.status, i.runner_id, r.name AS runner, i.thread_id,"
            " (SELECT count(*) FROM hub.instance_events e WHERE e.instance_id = i.id"
            "   AND e.processed_at IS NOT NULL) AS processed,"
            " (SELECT count(*) FROM hub.instance_events e WHERE e.instance_id = i.id"
            "   AND e.processed_at IS NULL) AS pending,"
            " (SELECT count(*) FROM hub.reports rep WHERE rep.instance_id = i.id) AS reports,"
            " (SELECT count(*) FROM hub.findings f WHERE f.instance_id = i.id) AS findings"
            " FROM hub.agent_instances i LEFT JOIN hub.runners r ON r.id = i.runner_id"
            " WHERE i.id = ANY(%s) ORDER BY i.id",
            ([ids["a"], ids["b"], ids["c"]],),
        ).fetchall()
    label = {ids["a"]: "A", ids["b"]: "B", ids["c"]: "C"}
    for row in rows:
        _p(
            f"   {label[row['id']]} (id={row['id']}): {row['status']:8}"
            f" runner={row['runner'] or '—':18} событий ✓{row['processed']}/⏳{row['pending']}"
            f" отчётов={row['reports']} находок={row['findings']}"
        )


async def repl(service: RunnerService, ids: dict[str, int]) -> None:
    last: Event | None = None
    _p(HELP)
    while True:
        try:
            line = (await asyncio.to_thread(input, "runner> ")).strip()
        except (EOFError, KeyboardInterrupt):
            line = "q"
        cmd, _, arg = line.partition(" ")
        arg = arg.strip().lower()
        match cmd.lower():
            case "":
                continue
            case "send":
                last = await publish_event(ids, arg if arg in ("a", "c") else "a")
            case "dup":
                if last is None:
                    _p("сначала send")
                else:
                    await publish_event(
                        ids, "a" if last.instance_id == ids["a"] else "c", dedup=last.dedup_key
                    )
            case "fwd":
                await publish_event(ids, "b")
            case "status":
                show_status(service, ids)
            case "chat":
                if not arg:
                    _p("chat <текст>")
                    continue
                async for mode, data in service.chat(ids["a"], arg):
                    _p(f"  💬 [{mode}] {json.dumps(data, ensure_ascii=False, default=str)}")
            case "stop":
                target = ids.get(arg or "a")
                _p(f"→ {(await service.stop_instance(target) and 'опущен') or 'не здесь'}")
            case "reap":
                await service.reap_idle()
                _p("→ idle-проход выполнен")
            case "wait":
                await asyncio.sleep(float(arg or 1))
            case "clean":
                clean_demo()
                return
            case "q" | "quit" | "exit":
                return
            case _:
                _p(HELP)


async def main() -> None:
    import logging

    for noisy in ("aio_pika", "aiormq", "httpx", "httpcore", "uvicorn", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _p("🚀 Демо Раннера: реальные Rabbit+Postgres, исполнение — DemoExecutor (без LLM).")
    ids = seed_demo()
    _p(
        f"🌱 засеяно: Экземпляры A={ids['a']} C={ids['c']} (наши), B={ids['b']}"
        f" (running у demo-runner-dead @ {DEAD_RUNNER_ADDRESS})"
    )

    # чистая очередь — прошлые демо-События не всплывают
    connection = await aio_pika.connect_robust(settings.rabbit_url)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue("events.runners", durable=True)
        await queue.purge()

    from infra.hub_client import HttpHubClient

    store = HubInstanceStore()
    hub = HttpHubClient(hub_url=settings.hub_url, token=settings.runner_token)
    service = RunnerService(
        store=store,
        hub=hub,
        executor=DemoExecutor(store),
        name="demo-runner",
        address=f"http://localhost:{settings.runner_port}",
        slots=SLOTS,
        idle_timeout_seconds=IDLE_SECONDS,
    )
    await service.start()

    import uvicorn
    from fastapi import FastAPI

    from infra.server.runner_api import api

    app = FastAPI()
    app.include_router(api)
    app.state.service = service
    server = uvicorn.Server(uvicorn.Config(app, port=settings.runner_port, log_level="warning"))
    background = [
        asyncio.create_task(consume_events(settings.rabbit_url, service.handle_event)),
        asyncio.create_task(service.idle_loop()),
        asyncio.create_task(server.serve()),
    ]
    _p(f"🌐 HTTP API: http://localhost:{settings.runner_port}/health\n")
    try:
        await repl(service, ids)
    finally:
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await service.shutdown()
        await hub.aclose()
        with contextlib.suppress(Exception):
            from infra.db.postgres import close_async_pool

            await close_async_pool()
        _p("👋 Экземпляры опущены, выхожу.")


if __name__ == "__main__":
    asyncio.run(main())
