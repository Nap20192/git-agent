"""PostgresRunStore — адаптер порта RunStore поверх infra.postgres.

Каждая мутация — один стейтмент (или короткая транзакция в claim): условный
UPDATE + RETURNING. Все сравнения времени — now() БАЗЫ, никакого clock skew.
Терминальные статусы не перезаписываются by construction: каждый терминальный
CAS охраняется условием на активный статус.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from core.runtime.schemas import (
    ConflictError,
    LeaseRenewal,
    RunStatus,
    StatusFinalization,
    SubmitDisposition,
)
from infra.postgres import get_async_pool

_ACTIVE = ("pending", "running")


class PostgresRunStore:
    async def claim(
        self,
        *,
        repository_id: int,
        commit_sha: str,
        llm_api_base: str,
        llm_api_key: str,
        llm_model: str,
        owner_worker_id: str,
        lease_seconds: int,
        grace_seconds: int,
    ) -> tuple[dict[str, Any], SubmitDisposition]:
        pool = await get_async_pool()
        async with pool.connection() as conn, conn.transaction():
            inserted = await (
                await conn.execute(
                    "INSERT INTO runs (repository_id, commit_sha, llm_api_base,"
                    " llm_api_key, llm_model, status, owner_worker_id, lease_expires_at)"
                    " VALUES (%s, %s, %s, %s, %s, 'pending', %s,"
                    "         now() + %s * interval '1 second')"
                    " ON CONFLICT (repository_id, commit_sha, llm_model) DO NOTHING"
                    " RETURNING *",
                    (
                        repository_id,
                        commit_sha,
                        llm_api_base,
                        llm_api_key,
                        llm_model,
                        owner_worker_id,
                        lease_seconds,
                    ),
                )
            ).fetchone()
            if inserted is not None:
                return inserted, SubmitDisposition.created

            row = await (
                await conn.execute(
                    "SELECT *, (lease_expires_at IS NOT NULL AND lease_expires_at >="
                    " now() - %s * interval '1 second') AS lease_valid"
                    " FROM runs WHERE repository_id = %s AND commit_sha = %s"
                    " AND llm_model = %s FOR UPDATE",
                    (grace_seconds, repository_id, commit_sha, llm_model),
                )
            ).fetchone()
            if row is None:  # гонка вставки/удаления; fail-closed
                raise ConflictError("run row vanished during claim")
            if row["status"] == "succeeded":
                return row, SubmitDisposition.already_succeeded
            if row["status"] in _ACTIVE and row["lease_valid"]:
                raise ConflictError(f"run {row['id']} is active with a valid lease")

            resumed = await (
                await conn.execute(
                    "UPDATE runs SET status = 'pending', owner_worker_id = %s,"
                    " lease_expires_at = now() + %s * interval '1 second',"
                    " llm_api_base = %s, llm_api_key = %s,"
                    " error = NULL, stop_reason = NULL, cancel_requested_at = NULL,"
                    " report = NULL, attempt = attempt + 1, started_at = now(),"
                    " finished_at = NULL, updated_at = now()"
                    " WHERE id = %s RETURNING *",
                    (owner_worker_id, lease_seconds, llm_api_base, llm_api_key, row["id"]),
                )
            ).fetchone()
            return resumed, SubmitDisposition.resumed

    async def get(self, run_id: int) -> dict[str, Any] | None:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            return await (
                await conn.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
            ).fetchone()

    async def delete_run(self, run_id: int) -> bool:
        """Удалить терминальный Ран: чекпоинты + события + строку (одна транзакция).

        Отказ (False) на активном (pending/running) Ране — его данные трогать
        нельзя. thread_id чекпоинтов = str(run_id).
        """
        from core.runtime.schemas import ACTIVE_STATUSES

        pool = await get_async_pool()
        async with pool.connection() as conn, conn.transaction():
            row = await (
                await conn.execute("SELECT status FROM runs WHERE id = %s FOR UPDATE", (run_id,))
            ).fetchone()
            if row is None:
                return False
            if row["status"] in {s.value for s in ACTIVE_STATUSES}:
                raise RuntimeError("cannot delete an active run; cancel it first")
            thread = str(run_id)
            await conn.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread,))
            await conn.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread,))
            await conn.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread,))
            await conn.execute("DELETE FROM run_events WHERE run_id = %s", (run_id,))
            await conn.execute("DELETE FROM runs WHERE id = %s", (run_id,))
            return True

    async def start_run(self, run_id: int, *, owner_worker_id: str) -> bool:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE runs SET status = 'running', updated_at = now()"
                " WHERE id = %s AND status = 'pending' AND owner_worker_id = %s",
                (run_id, owner_worker_id),
            )
            return cur.rowcount == 1

    async def renew_lease(
        self, run_id: int, *, owner_worker_id: str, lease_seconds: int
    ) -> LeaseRenewal:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "UPDATE runs SET lease_expires_at = now() + %s * interval '1 second',"
                    " updated_at = now()"
                    " WHERE id = %s AND owner_worker_id = %s"
                    " AND status IN ('pending', 'running')"
                    " RETURNING cancel_requested_at",
                    (lease_seconds, run_id, owner_worker_id),
                )
            ).fetchone()
        if row is None:
            return LeaseRenewal(renewed=False)
        return LeaseRenewal(renewed=True, cancel_requested=row["cancel_requested_at"] is not None)

    async def request_cancel(self, run_id: int) -> bool:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE runs SET cancel_requested_at = now(), updated_at = now()"
                " WHERE id = %s AND status IN ('pending', 'running')"
                " AND cancel_requested_at IS NULL",
                (run_id,),
            )
            if cur.rowcount == 1:
                return True
            # rowcount 0: отличить «запрос уже висит» (True) от терминального/нет (False)
            row = await (
                await conn.execute(
                    "SELECT status, cancel_requested_at FROM runs WHERE id = %s", (run_id,)
                )
            ).fetchone()
        return bool(row and row["status"] in _ACTIVE and row["cancel_requested_at"] is not None)

    async def finalize_if_not_cancelled(
        self, run_id: int, *, owner_worker_id: str, report: dict[str, Any] | None
    ) -> StatusFinalization:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE runs SET status = 'succeeded', report = %s,"
                " finished_at = now(), updated_at = now()"
                " WHERE id = %s AND status = 'running' AND owner_worker_id = %s"
                " AND cancel_requested_at IS NULL",
                (Jsonb(report) if report is not None else None, run_id, owner_worker_id),
            )
            if cur.rowcount == 1:
                return StatusFinalization(finalized=True)
            row = await (
                await conn.execute(
                    "SELECT status, cancel_requested_at FROM runs WHERE id = %s", (run_id,)
                )
            ).fetchone()
        if row and row["status"] in _ACTIVE and row["cancel_requested_at"] is not None:
            return StatusFinalization(finalized=False, cancelled=True)
        return StatusFinalization(finalized=False)

    async def finish(
        self,
        run_id: int,
        *,
        owner_worker_id: str,
        status: str,
        error: str | None = None,
        stop_reason: str | None = None,
    ) -> bool:
        if status not in (RunStatus.failed, RunStatus.interrupted):
            raise ValueError(f"finish() only writes failed|interrupted, got {status!r}")
        pool = await get_async_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE runs SET status = %s, error = %s, stop_reason = %s,"
                " finished_at = now(), updated_at = now()"
                " WHERE id = %s AND status IN ('pending', 'running')"
                " AND owner_worker_id = %s",
                (status, error, stop_reason, run_id, owner_worker_id),
            )
            return cur.rowcount == 1

    async def claim_for_takeover(
        self, run_id: int, *, grace_seconds: int, error: str, stop_reason: str
    ) -> bool:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE runs SET status = 'failed', error = %s, stop_reason = %s,"
                " owner_worker_id = NULL, finished_at = now(), updated_at = now()"
                " WHERE id = %s AND status IN ('pending', 'running')"
                " AND (lease_expires_at IS NULL OR"
                "      lease_expires_at < now() - %s * interval '1 second')",
                (error, stop_reason, run_id, grace_seconds),
            )
            return cur.rowcount == 1

    async def list_expired(self, *, grace_seconds: int) -> list[dict[str, Any]]:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            return await (
                await conn.execute(
                    "SELECT * FROM runs WHERE status IN ('pending', 'running')"
                    " AND (lease_expires_at IS NULL OR"
                    "      lease_expires_at < now() - %s * interval '1 second')",
                    (grace_seconds,),
                )
            ).fetchall()

    async def add_event(self, run_id: int, kind: str, payload: dict[str, Any]) -> None:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO run_events (run_id, kind, payload) VALUES (%s, %s, %s)",
                (run_id, kind, Jsonb(payload)),
            )

    async def list_events_after(
        self, run_id: int, after_id: int | None, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        pool = await get_async_pool()
        async with pool.connection() as conn:
            return await (
                await conn.execute(
                    "SELECT * FROM run_events WHERE run_id = %s AND id > %s ORDER BY id LIMIT %s",
                    (run_id, after_id or 0, limit),
                )
            ).fetchall()
