"""Порт-тесты RunStore против реального Postgres (те же сценарии, что memory)."""

import asyncio
import uuid

import psycopg
import pytest

from core.config import settings
from core.runtime import ConflictError, RunStatus, SubmitDisposition
from infra.run_store import PostgresRunStore


def _pg_available() -> bool:
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="postgres is not running")


def _claim_kwargs(**over):
    return (
        dict(
            repository_id=1,
            commit_sha=f"pgtest-{uuid.uuid4().hex[:12]}",
            llm_api_base="http://x",
            llm_api_key="k",
            llm_model="m",
            owner_worker_id="w1",
            lease_seconds=30,
            grace_seconds=10,
        )
        | over
    )


def _expire_lease(run_id: int) -> None:
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            "UPDATE runs SET lease_expires_at = now() - interval '999 seconds' WHERE id = %s",
            (run_id,),
        )


def test_pg_claim_conflict_takeover_succeed():
    async def main():
        store = PostgresRunStore()
        kwargs = _claim_kwargs()
        row, disp = await store.claim(**kwargs)
        assert disp == SubmitDisposition.created

        with pytest.raises(ConflictError):
            await store.claim(**kwargs)

        _expire_lease(row["id"])
        row2, disp2 = await store.claim(**kwargs | {"owner_worker_id": "w2"})
        assert disp2 == SubmitDisposition.resumed and row2["attempt"] == 2

        assert await store.start_run(row["id"], owner_worker_id="w2")
        fin = await store.finalize_if_not_cancelled(
            row["id"], owner_worker_id="w2", report={"ok": 1}
        )
        assert fin.finalized
        row3, disp3 = await store.claim(**kwargs)
        assert disp3 == SubmitDisposition.already_succeeded and row3["report"] == {"ok": 1}

    asyncio.run(main())


def test_pg_cancel_mailbox_and_terminal_immutability():
    async def main():
        store = PostgresRunStore()
        kwargs = _claim_kwargs()
        row, _ = await store.claim(**kwargs)
        run_id = row["id"]
        assert await store.start_run(run_id, owner_worker_id="w1")
        assert await store.request_cancel(run_id)
        assert await store.request_cancel(run_id)  # повторный: уже висит → True

        renewal = await store.renew_lease(run_id, owner_worker_id="w1", lease_seconds=30)
        assert renewal.renewed and renewal.cancel_requested

        fin = await store.finalize_if_not_cancelled(run_id, owner_worker_id="w1", report={})
        assert not fin.finalized and fin.cancelled

        assert await store.finish(
            run_id, owner_worker_id="w1", status=RunStatus.interrupted, stop_reason="cancelled"
        )
        # терминальный статус неперезаписываем
        assert not await store.finish(
            run_id, owner_worker_id="w1", status=RunStatus.failed, error="late"
        )
        assert not await store.claim_for_takeover(
            run_id, grace_seconds=0, error="x", stop_reason="y"
        )
        assert (await store.get(run_id))["status"] == "interrupted"

    asyncio.run(main())


def test_pg_orphan_scan_and_renew_fencing():
    async def main():
        store = PostgresRunStore()
        row, _ = await store.claim(**_claim_kwargs(owner_worker_id="dead"))
        run_id = row["id"]
        _expire_lease(run_id)

        expired_ids = {r["id"] for r in await store.list_expired(grace_seconds=10)}
        assert run_id in expired_ids

        assert await store.claim_for_takeover(
            run_id, grace_seconds=10, error="orphan", stop_reason="orphan_recovered"
        )
        renewal = await store.renew_lease(run_id, owner_worker_id="dead", lease_seconds=30)
        assert not renewal.renewed  # бывший владелец фенсится

    asyncio.run(main())


def test_pg_events_cursor():
    async def main():
        store = PostgresRunStore()
        row, _ = await store.claim(**_claim_kwargs())
        run_id = row["id"]
        for i in range(3):
            await store.add_event(run_id, "updates", {"i": i})
        events = await store.list_events_after(run_id, None)
        assert [e["payload"]["i"] for e in events] == [0, 1, 2]
        tail = await store.list_events_after(run_id, events[0]["id"])
        assert [e["payload"]["i"] for e in tail] == [1, 2]

    asyncio.run(main())
