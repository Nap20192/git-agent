"""Python-зеркала теорем formal/RuntimeCore.lean (карта — formal/MAPPING.md)."""

import asyncio
import random
from datetime import UTC, datetime, timedelta

import pytest

from core.runtime import ConflictError, MemoryRunStore, RunStatus
from core.runtime.schemas import (
    ACTIVE_STATUSES,
    LEGAL_TRANSITIONS,
    TERMINAL_STATUSES,
    assert_transition,
)

CLAIM = dict(
    repository_id=1,
    commit_sha="abc",
    llm_api_base="http://x",
    llm_api_key="k",
    llm_model="m",
    owner_worker_id="w1",
    lease_seconds=30,
    grace_seconds=10,
)


# -- Lean: step_target_sound --------------------------------------------------


def test_step_targets_sound_mirror():
    for source, targets in LEGAL_TRANSITIONS.items():
        for target in targets:
            assert (
                target is RunStatus.running
                or target in TERMINAL_STATUSES
                or (target is RunStatus.pending and source in TERMINAL_STATUSES)
            ), (source, target)
    assert set(LEGAL_TRANSITIONS) == set(RunStatus)


def test_assert_transition_guards():
    assert_transition(RunStatus.pending, RunStatus.running)
    assert_transition(RunStatus.failed, RunStatus.pending, via_claim=True)
    with pytest.raises(AssertionError):
        assert_transition(RunStatus.succeeded, RunStatus.pending, via_claim=True)
    with pytest.raises(AssertionError):
        assert_transition(RunStatus.failed, RunStatus.pending)
    with pytest.raises(AssertionError):
        assert_transition(RunStatus.running, RunStatus.pending)


# -- Lean: terminal_absorbing -------------------------------------------------


def test_terminal_absorbing_mirror():
    async def main():
        store = MemoryRunStore()
        row, _ = await store.claim(**CLAIM)
        rid = row["id"]
        await store.start_run(rid, owner_worker_id="w1")
        await store.finalize_if_not_cancelled(rid, owner_worker_id="w1", report={})
        assert not await store.start_run(rid, owner_worker_id="w1")
        assert not await store.finish(rid, owner_worker_id="w1", status=RunStatus.failed)
        assert not await store.claim_for_takeover(rid, grace_seconds=0, error="x", stop_reason="y")
        _, disp = await store.claim(**CLAIM)
        assert disp.value == "already_succeeded"
        assert (await store.get(rid))["status"] == RunStatus.succeeded

    asyncio.run(main())


# -- Lean: exclusive ----------------------------------------------------------


def test_exclusive_mirror():
    async def main():
        store = MemoryRunStore()
        row, _ = await store.claim(**CLAIM)
        with pytest.raises(ConflictError):
            await store.claim(**{**CLAIM, "owner_worker_id": "w2"})
        assert not await store.start_run(row["id"], owner_worker_id="w2")

    asyncio.run(main())


# -- Lean: inv_preserved (рандомизированные последовательности) ---------------


def _admission_invariant(store: MemoryRunStore) -> None:
    """Invariant: каждый running-ран держит admission (owner_worker_id)."""
    active_by_identity: dict[tuple, int] = {}
    for row in store._runs.values():
        if row["status"] == RunStatus.running:
            assert row["owner_worker_id"] is not None, row
        if row["status"] in ACTIVE_STATUSES:
            key = (row["repository_id"], row["commit_sha"], row["llm_model"])
            assert key not in active_by_identity, f"two active runs for {key}"
            active_by_identity[key] = row["id"]


def test_admission_invariant_mirror():
    async def main():
        rng = random.Random(42)
        store = MemoryRunStore()
        _admission_invariant(store)
        identities = [dict(CLAIM, commit_sha=f"c{i}") for i in range(3)]
        workers = ["w1", "w2"]
        for _ in range(400):
            op = rng.randrange(6)
            ident = dict(rng.choice(identities), owner_worker_id=rng.choice(workers))
            run_ids = list(store._runs)
            rid = rng.choice(run_ids) if run_ids else 1
            worker = rng.choice(workers)
            try:
                if op == 0:
                    await store.claim(**ident)
                elif op == 1:
                    await store.start_run(rid, owner_worker_id=worker)
                elif op == 2:
                    await store.finalize_if_not_cancelled(rid, owner_worker_id=worker, report=None)
                elif op == 3:
                    await store.finish(
                        rid,
                        owner_worker_id=worker,
                        status=rng.choice([RunStatus.failed, RunStatus.interrupted]),
                    )
                elif op == 4:
                    await store.request_cancel(rid)
                elif op == 5 and run_ids and rng.random() < 0.3:
                    store._runs[rid]["lease_expires_at"] = datetime.now(UTC) - timedelta(
                        seconds=999
                    )
                    await store.claim_for_takeover(
                        rid, grace_seconds=10, error="orphan", stop_reason="orphan_recovered"
                    )
            except ConflictError:
                pass
            _admission_invariant(store)

    asyncio.run(main())
