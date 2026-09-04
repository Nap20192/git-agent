"""Postgres-адаптер порта InstanceStore: операции раннера над схемой hub.*."""

from __future__ import annotations

from typing import Any

from psycopg.errors import UndefinedColumn
from psycopg.types.json import Json

from core.runner.events import Event
from core.runner.ports import ClaimResult
from infra.db.postgres import get_async_pool
from pkg.logger import get_logger

log = get_logger(__name__)

_CONTEXT_SQL = """
    SELECT i.id, i.thread_id, i.build_id, i.repository_id, i.sandbox_instance_id,
           b.prompt, b.memory_preset, b.limits,
           l.api_base  AS llm_api_base,
           l.api_key_enc AS llm_api_key_enc,
           l.model     AS llm_model,
           l.params    AS llm_params,
           sc.id       AS sandbox_connection_id,
           sc.domain   AS sandbox_domain,
           sc.api_key_enc AS sandbox_api_key_enc,
           sc.image    AS sandbox_image,
           repo.provider, repo.owner, repo.name,
           si.external_id AS sandbox_external_id,
           si.status      AS sandbox_status
    FROM hub.agent_instances i
    JOIN hub.agent_builds b        ON b.id = i.build_id
    JOIN hub.llm_connections l     ON l.id = b.llm_connection_id
    JOIN hub.sandbox_connections sc ON sc.id = b.sandbox_connection_id
    JOIN hub.repositories repo     ON repo.id = i.repository_id
    LEFT JOIN hub.sandbox_instances si ON si.id = i.sandbox_instance_id
    WHERE i.id = %s
"""


class HubInstanceStore:
    async def register_runner(self, *, name: str, address: str, slots: int) -> int:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "INSERT INTO hub.runners (name, address, slots) VALUES (%s, %s, %s)"
                    " ON CONFLICT (name) DO UPDATE SET address = EXCLUDED.address,"
                    " slots = EXCLUDED.slots, last_heartbeat_at = now() RETURNING id",
                    (name, address, slots),
                )
            ).fetchone()
        return row["id"]

    async def heartbeat_runner(self, runner_id: int) -> None:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE hub.runners SET last_heartbeat_at = now() WHERE id = %s", (runner_id,)
            )

    async def claim_instance(self, instance_id: int, *, runner_id: int) -> ClaimResult:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "UPDATE hub.agent_instances SET status = 'running', runner_id = %s,"
                    " updated_at = now() WHERE id = %s AND (status = 'down' OR runner_id = %s)"
                    " RETURNING id",
                    (runner_id, instance_id, runner_id),
                )
            ).fetchone()
            if row is not None:
                return ClaimResult("claimed")
            holder = await (
                await conn.execute(
                    "SELECT i.runner_id, r.address FROM hub.agent_instances i"
                    " LEFT JOIN hub.runners r ON r.id = i.runner_id WHERE i.id = %s",
                    (instance_id,),
                )
            ).fetchone()
        if holder is None:
            return ClaimResult("missing")
        return ClaimResult("held_by_other", holder_address=holder["address"])

    async def peek_holder(self, instance_id: int, *, runner_id: int) -> ClaimResult:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT i.status, i.runner_id, r.address FROM hub.agent_instances i"
                    " LEFT JOIN hub.runners r ON r.id = i.runner_id WHERE i.id = %s",
                    (instance_id,),
                )
            ).fetchone()
        if row is None:
            return ClaimResult("missing")
        if row["status"] != "running":
            return ClaimResult("free")
        if row["runner_id"] == runner_id:
            return ClaimResult("held_by_self")
        return ClaimResult("held_by_other", holder_address=row["address"])

    async def release_instance(self, instance_id: int, *, runner_id: int) -> bool:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "UPDATE hub.agent_instances SET status = 'down', runner_id = NULL,"
                    " updated_at = now() WHERE id = %s AND runner_id = %s AND status = 'running'"
                    " RETURNING id",
                    (instance_id, runner_id),
                )
            ).fetchone()
        return row is not None

    async def begin_event(self, event: Event) -> bool:
        # upsert-читка: NULL processed_at = обрабатывать (свежее или ре-публикация)
        pool = await get_async_pool()
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "INSERT INTO hub.instance_events (instance_id, event_id, dedup_key)"
                    " VALUES (%s, %s, %s) ON CONFLICT (instance_id, dedup_key)"
                    " DO UPDATE SET dedup_key = EXCLUDED.dedup_key RETURNING processed_at",
                    (event.instance_id, event.event_id, event.dedup_key),
                )
            ).fetchone()
        return row["processed_at"] is None

    async def mark_processed(self, instance_id: int, dedup_key: str) -> None:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE hub.instance_events SET processed_at = now()"
                " WHERE instance_id = %s AND dedup_key = %s",
                (instance_id, dedup_key),
            )

    async def load_context(self, instance_id: int) -> dict[str, Any] | None:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            return await (await conn.execute(_CONTEXT_SQL, (instance_id,))).fetchone()

    async def mark_sandbox_dead(self, sandbox_instance_id: int) -> None:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE hub.sandbox_instances SET status = 'dead', killed_at = now() WHERE id = %s",
                (sandbox_instance_id,),
            )

    async def add_report(
        self,
        instance_id: int,
        *,
        event_id: int | None,
        summary: str,
        structured: dict[str, Any] | None = None,
    ) -> int:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            try:
                row = await (
                    await conn.execute(
                        "INSERT INTO hub.reports (instance_id, event_id, summary, structured)"
                        " VALUES (%s, %s, %s, %s) RETURNING id",
                        (instance_id, event_id, summary, Json(structured) if structured else None),
                    )
                ).fetchone()
            except UndefinedColumn:  # hub.reports.structured — миграция 007 hub'а ещё не применена
                await conn.rollback()
                _warn_schema_v1("hub.reports.structured")
                row = await (
                    await conn.execute(
                        "INSERT INTO hub.reports (instance_id, event_id, summary)"
                        " VALUES (%s, %s, %s) RETURNING id",
                        (instance_id, event_id, summary),
                    )
                ).fetchone()
        return row["id"]

    async def add_finding(
        self, instance_id: int, finding: dict[str, Any], *, event_id: int | None = None
    ) -> None:
        pool = await get_async_pool()
        v1 = (
            instance_id,
            finding.get("severity") or "info",
            finding.get("cwe"),
            finding.get("cve"),
            finding.get("file"),
            finding.get("lineStart"),
            finding.get("lineEnd"),
            _evidence(
                finding
            ),  # по-прежнему несёт title/description/impact для UI на старых колонках
            finding.get("remediation"),
        )
        v2 = (
            finding.get("title"),
            finding.get("description"),
            finding.get("impact"),
            finding.get("confidence"),
            finding.get("category"),
            Json(finding.get("references") or []),
            finding.get("blameAuthor"),
            finding.get("blameEmail"),
            finding.get("blameCommit"),
            finding.get("blameDate"),
            finding.get("blameCommitMessage"),
            finding.get("introducedBy"),
        )
        async with pool.connection() as conn:
            try:
                await conn.execute(
                    "INSERT INTO hub.findings (instance_id, event_id, severity, cwe, cve, file,"
                    " line_start, line_end, evidence, remediation, title, description, impact,"
                    ' confidence, category, "references", blame_author, blame_email,'
                    " blame_commit, blame_date, blame_commit_message, introduced_by)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                    " %s, %s, %s, %s, %s)",
                    (v1[0], event_id, *v1[1:], *v2),
                )
            except UndefinedColumn:  # колонки Находки v2 — миграция 007 hub'а ещё не применена
                await conn.rollback()
                _warn_schema_v1("hub.findings v2 columns")
                await conn.execute(
                    "INSERT INTO hub.findings (instance_id, event_id, severity, cwe, cve, file,"
                    " line_start, line_end, evidence, remediation)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (v1[0], event_id, *v1[1:]),
                )

    async def add_activity(
        self,
        instance_id: int,
        *,
        event_id: int | None,
        seq: int,
        frame: dict[str, Any],
        trace_id: str = "",
    ) -> None:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO hub.activity (instance_id, event_id, seq, kind, payload, trace_id)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (instance_id, event_id, seq, frame.get("kind", ""), Json(frame), trace_id),
            )

    async def list_activity(
        self, instance_id: int, *, event_id: int | None = None, latest: bool = False
    ) -> list[dict[str, Any]]:
        if latest:
            where = (
                "event_id IS NOT DISTINCT FROM (SELECT event_id FROM hub.activity"
                " WHERE instance_id = %s ORDER BY id DESC LIMIT 1)"
            )
            params: tuple[Any, ...] = (instance_id, instance_id)
        else:
            where = "event_id IS NOT DISTINCT FROM %s"
            params = (instance_id, event_id)
        pool = await get_async_pool()
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT payload FROM hub.activity"
                    f" WHERE instance_id = %s AND {where} ORDER BY seq, id",
                    params,
                )
            ).fetchall()
        return [row["payload"] for row in rows]


_warned_schema: set[str] = set()


def _warn_schema_v1(what: str) -> None:
    """Один warning на процесс: пишем по схеме v1, поля v2 теряются до миграции 007."""
    if what not in _warned_schema:
        _warned_schema.add(what)
        log.warning("hub schema is v1, falling back (apply hub migration 007)", missing=what)


def _evidence(finding: dict[str, Any]) -> str:
    """title/description/impact/confidence живут в evidence — в hub.findings нет колонок."""
    parts = [
        finding.get("title") or "",
        finding.get("description") or "",
        finding.get("impact") or "",
        finding.get("evidence") or "",
        f"confidence: {finding['confidence']}" if finding.get("confidence") else "",
    ]
    return "\n\n".join(p for p in parts if p)
