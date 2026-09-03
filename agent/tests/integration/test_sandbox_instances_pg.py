"""PG-CRUD Экземпляров Сэндбокса против реального Postgres."""

import asyncio
import uuid

import psycopg
import pytest

from core.config import settings
from infra.db.run_store import PostgresRunStore
from infra.sandbox import instances as si


def _new_run_id() -> int:
    """Реальный ран (FK sandbox_instances.run_id → runs.id) через store.claim."""

    async def _mk() -> int:
        row, _ = await PostgresRunStore().claim(
            repository_id=1,
            commit_sha=f"sbxtest-{uuid.uuid4().hex[:12]}",
            llm_api_base="http://x",
            llm_api_key="k",
            llm_model="m",
            owner_worker_id="w1",
            lease_seconds=30,
            grace_seconds=10,
        )
        return row["id"]

    return asyncio.run(_mk())


def _pg_available() -> bool:
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="postgres is not running")


def test_record_list_alive_and_mark_dead():
    ext = f"sbx-{uuid.uuid4().hex[:12]}"
    row = si.record_instance(ext, "opensandbox", "alpine/git:latest", None)
    assert row["status"] == "alive" and row["external_id"] == ext and row["killed_at"] is None

    assert any(r["external_id"] == ext for r in si.list_instances())

    dead = si.mark_dead(ext)
    assert dead["status"] == "dead" and dead["killed_at"] is not None
    again = si.mark_dead(ext)
    assert again["status"] == "dead" and again["killed_at"] == dead["killed_at"]


def test_alive_instance_for_run_picks_latest_alive():
    run_id = _new_run_id()
    old = si.record_instance(f"o-{uuid.uuid4().hex[:10]}", "opensandbox", None, run_id)
    si.mark_dead(old["external_id"])
    fresh = si.record_instance(f"n-{uuid.uuid4().hex[:10]}", "opensandbox", None, run_id)

    picked = si.alive_instance_for_run(run_id)
    assert picked is not None and picked["external_id"] == fresh["external_id"]
