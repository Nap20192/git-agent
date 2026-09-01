"""Тесты инвариантов рантайма: memory-store как исполняемая спецификация порта."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from core.runtime import (
    END_SENTINEL,
    CancelOutcome,
    ConflictError,
    MemoryRunStore,
    MemoryStreamBridge,
    RunStartOutcome,
    RunStatus,
    Runtime,
    StreamGap,
    SubmitDisposition,
)
from core.runtime.manager import RunManager
from core.runtime.serialization import serialize, serialize_channel_values

IDENTITY = dict(
    repository_id=1,
    commit_sha="abc",
    llm_api_base="http://x",
    llm_api_key="k",
    llm_model="m",
)
CLAIM = dict(**IDENTITY, owner_worker_id="w1", lease_seconds=30, grace_seconds=10)


def _expire_lease(store: MemoryRunStore, run_id: int) -> None:
    store._runs[run_id]["lease_expires_at"] = datetime.now(UTC) - timedelta(seconds=999)


# -- claim -------------------------------------------------------------------


def test_claim_lifecycle():
    async def main():
        store = MemoryRunStore()
        row, disp = await store.claim(**CLAIM)
        assert disp == SubmitDisposition.created and row["attempt"] == 1

        # активный ран с валидным lease → конфликт
        with pytest.raises(ConflictError):
            await store.claim(**CLAIM)

        # истёкший lease → takeover-resume
        _expire_lease(store, row["id"])
        row2, disp2 = await store.claim(**{**CLAIM, "owner_worker_id": "w2"})
        assert disp2 == SubmitDisposition.resumed
        assert row2["attempt"] == 2 and row2["owner_worker_id"] == "w2"

        # succeeded → already_succeeded, без мутации
        await store.start_run(row["id"], owner_worker_id="w2")
        fin = await store.finalize_if_not_cancelled(
            row["id"], owner_worker_id="w2", report={"ok": 1}
        )
        assert fin.finalized
        row3, disp3 = await store.claim(**CLAIM)
        assert disp3 == SubmitDisposition.already_succeeded
        assert row3["report"] == {"ok": 1}

    asyncio.run(main())


def test_resume_clears_stale_cancel_and_error():
    async def main():
        store = MemoryRunStore()
        row, _ = await store.claim(**CLAIM)
        await store.start_run(row["id"], owner_worker_id="w1")
        await store.request_cancel(row["id"])
        await store.finish(
            row["id"], owner_worker_id="w1", status=RunStatus.interrupted, stop_reason="cancelled"
        )
        row2, disp = await store.claim(**CLAIM)
        assert disp == SubmitDisposition.resumed
        assert row2["cancel_requested_at"] is None
        assert row2["error"] is None and row2["stop_reason"] is None

    asyncio.run(main())


# -- CAS guards --------------------------------------------------------------


def test_start_run_cas():
    async def main():
        store = MemoryRunStore()
        row, _ = await store.claim(**CLAIM)
        assert not await store.start_run(row["id"], owner_worker_id="intruder")
        assert await store.start_run(row["id"], owner_worker_id="w1")
        assert not await store.start_run(row["id"], owner_worker_id="w1")  # не pending

    asyncio.run(main())


def test_terminal_status_never_overwritten():
    async def main():
        store = MemoryRunStore()
        row, _ = await store.claim(**CLAIM)
        await store.start_run(row["id"], owner_worker_id="w1")
        await store.finalize_if_not_cancelled(row["id"], owner_worker_id="w1", report=None)
        assert not await store.finish(
            row["id"], owner_worker_id="w1", status=RunStatus.failed, error="late"
        )
        assert not await store.claim_for_takeover(
            row["id"], grace_seconds=0, error="x", stop_reason="y"
        )
        assert (await store.get(row["id"]))["status"] == RunStatus.succeeded

    asyncio.run(main())


def test_cancel_beats_finalize():
    async def main():
        store = MemoryRunStore()
        row, _ = await store.claim(**CLAIM)
        await store.start_run(row["id"], owner_worker_id="w1")
        assert await store.request_cancel(row["id"])
        renewal = await store.renew_lease(row["id"], owner_worker_id="w1", lease_seconds=30)
        assert renewal.renewed and renewal.cancel_requested  # heartbeat = mailbox
        fin = await store.finalize_if_not_cancelled(
            row["id"], owner_worker_id="w1", report={"r": 1}
        )
        assert not fin.finalized and fin.cancelled

    asyncio.run(main())


def test_renew_after_takeover_loses_ownership():
    async def main():
        store = MemoryRunStore()
        row, _ = await store.claim(**CLAIM)
        _expire_lease(store, row["id"])
        assert await store.claim_for_takeover(
            row["id"], grace_seconds=10, error="orphan", stop_reason="orphan_recovered"
        )
        renewal = await store.renew_lease(row["id"], owner_worker_id="w1", lease_seconds=30)
        assert not renewal.renewed

    asyncio.run(main())


# -- manager -----------------------------------------------------------------


def test_try_start_post_await_abort_restores_durable():
    async def main():
        store = MemoryRunStore()
        manager = RunManager(store, worker_id="w1")
        result = await manager.admit(**IDENTITY)
        record = manager.get_local(result.run["id"])
        record.abort_event.set()  # отмена «в полёте» до try_start
        assert await manager.try_start(result.run["id"]) is RunStartOutcome.cancelled
        row = await store.get(result.run["id"])
        assert row["status"] in (RunStatus.pending, RunStatus.interrupted)
        assert row["status"] != RunStatus.running  # durable не остаётся running

    asyncio.run(main())


def test_orphan_reconcile_and_local_skip():
    async def main():
        store = MemoryRunStore()
        manager = RunManager(store, worker_id="w1")
        mine = await manager.admit(**IDENTITY)
        # чужой осиротевший ран
        other, _ = await store.claim(**{**CLAIM, "repository_id": 2, "owner_worker_id": "dead"})
        _expire_lease(store, other["id"])
        _expire_lease(store, mine.run["id"])  # наш тоже истёк, но локально жив
        recovered = await manager.reconcile_orphans()
        assert other["id"] in recovered and mine.run["id"] not in recovered
        assert (await store.get(other["id"]))["stop_reason"] == "orphan_recovered"

    asyncio.run(main())


def test_cancel_outcomes():
    async def main():
        store = MemoryRunStore()
        manager = RunManager(store, worker_id="w1")
        assert await manager.cancel(999) is CancelOutcome.not_found

        # чужой ран с валидным lease → requested
        row, _ = await store.claim(**{**CLAIM, "owner_worker_id": "other"})
        assert await manager.cancel(row["id"]) is CancelOutcome.requested
        assert (await store.get(row["id"]))["cancel_requested_at"] is not None

        # чужой ран с истёкшим lease → taken_over
        row2, _ = await store.claim(**{**CLAIM, "repository_id": 7, "owner_worker_id": "other"})
        _expire_lease(store, row2["id"])
        assert await manager.cancel(row2["id"]) is CancelOutcome.taken_over
        assert (await store.get(row2["id"]))["status"] == RunStatus.failed

    asyncio.run(main())


# -- bridge ------------------------------------------------------------------


def test_bridge_replay_exclusive_and_end():
    async def main():
        bridge = MemoryStreamBridge()
        for i in range(3):
            await bridge.publish(1, "updates", {"i": i})
        await bridge.publish_end(1)

        seen = []
        cursor = None
        async for item in bridge.subscribe(1):
            if item is END_SENTINEL:
                break
            seen.append(item.data["i"])
            cursor = item.id
        assert seen == [0, 1, 2]

        # реплей с курсора эксклюзивен: после последнего события — сразу END
        tail = []
        async for item in bridge.subscribe(1, last_event_id=cursor):
            if item is END_SENTINEL:
                break
            tail.append(item)
        assert tail == []

    asyncio.run(main())


def test_bridge_below_watermark_gap():
    async def main():
        bridge = MemoryStreamBridge(maxsize=2)
        first_id = None
        for i in range(5):
            await bridge.publish(1, "updates", {"i": i})
            if i == 0:
                first_id = bridge._streams[1].events[0].id
        items = []
        async for item in bridge.subscribe(1, last_event_id=first_id):
            items.append(item)
            break
        assert isinstance(items[0], StreamGap)
        assert items[0].requested_event_id == first_id

    asyncio.run(main())


def test_bridge_stale_cursor_from_previous_incarnation():
    async def main():
        bridge = MemoryStreamBridge()
        await bridge.publish(1, "updates", {"old": True})
        stale = bridge._streams[1].events[0].id
        await bridge.cleanup(1)
        await asyncio.sleep(0.002)  # новая инкарнация: другой timestamp в id
        await bridge.publish(1, "updates", {"new": True})
        await bridge.publish_end(1)
        seen = []
        async for item in bridge.subscribe(1, last_event_id=stale):
            if item is END_SENTINEL:
                break
            seen.append(item)
        # id не совпал по вотермарке → реплей с раннего, «новое» событие не потеряно
        assert len(seen) == 1 and seen[0].data == {"new": True}

    asyncio.run(main())


# -- serialization -----------------------------------------------------------


def test_serialize_interrupt_and_pregel_strip():
    from langgraph.types import Interrupt

    out = serialize(Interrupt(value={"q": "?"}))
    assert out["value"] == {"q": "?"}

    values = serialize_channel_values(
        {"__pregel_tasks": [1], "__interrupt__": ["x"], "messages": ["m"]}
    )
    assert "__pregel_tasks" not in values
    assert values["__interrupt__"] == ["x"] and values["messages"] == ["m"]


def test_serialize_never_raises():
    class Exploding:
        def model_dump(self):
            raise RuntimeError("boom")

        def __str__(self):
            return "exploding"

    assert serialize(Exploding()) == "exploding"


# -- end-to-end через фасад ---------------------------------------------------


class _FakeState:
    def __init__(self, values):
        self.values = values


class _FakeGraph:
    def __init__(self, chunks, report):
        self._chunks = chunks
        self._report = report

    async def astream(self, graph_input, config=None, stream_mode=None):
        for chunk in self._chunks:
            await asyncio.sleep(0)
            yield "updates", chunk

    async def aget_state(self, config):
        return _FakeState({"report": self._report})


class _FakeSandbox:
    repo_dir = "/repo"

    async def run(self, command, *, timeout_seconds=None):
        return ""

    async def close(self):
        pass


def _make_runtime(store, bridge, report=None, chunks=()):
    async def fake_repo(url):
        return {"id": 1, "url": url}

    async def fake_sandbox(name):
        return _FakeSandbox()

    return Runtime(
        store=store,
        bridge=bridge,
        build_graph=lambda sb, m, checkpointer=None: _FakeGraph(list(chunks), report),
        make_model=lambda **kw: object(),
        create_sandbox=fake_sandbox,
        get_or_create_repository=fake_repo,
    )


def test_runtime_submit_success_and_idempotency():
    async def main():
        store, bridge = MemoryRunStore(), MemoryStreamBridge()
        rt = _make_runtime(store, bridge, report={"done": True}, chunks=[{"scan": {"files": 1}}])
        result = await rt.submit(
            repo_url="u", commit_sha="c", llm_api_base="b", llm_api_key="k", llm_model="m"
        )
        assert result.disposition == SubmitDisposition.created
        final = await rt.wait(result.run["id"])
        assert final["status"] == RunStatus.succeeded
        assert final["report"] == {"done": True}

        again = await rt.submit(
            repo_url="u", commit_sha="c", llm_api_base="b", llm_api_key="k", llm_model="m"
        )
        assert again.disposition == SubmitDisposition.already_succeeded

        events = await rt.events(result.run["id"])
        assert [e["kind"] for e in events] == ["updates"]

    asyncio.run(main())


def test_runtime_report_error_means_failed_and_resume():
    async def main():
        store, bridge = MemoryRunStore(), MemoryStreamBridge()
        rt = _make_runtime(store, bridge, report={"error": "clone failed"})
        result = await rt.submit(
            repo_url="u", commit_sha="c", llm_api_base="b", llm_api_key="k", llm_model="m"
        )
        final = await rt.wait(result.run["id"])
        assert final["status"] == RunStatus.failed

        rt2 = _make_runtime(store, bridge, report={"done": 1})
        resumed = await rt2.submit(
            repo_url="u", commit_sha="c", llm_api_base="b", llm_api_key="k", llm_model="m"
        )
        assert resumed.disposition == SubmitDisposition.resumed
        assert resumed.run["id"] == result.run["id"]  # тот же Ран
        final2 = await rt2.wait(resumed.run["id"])
        assert final2["status"] == RunStatus.succeeded and final2["attempt"] == 2

    asyncio.run(main())


def test_runtime_cancel_midflight():
    async def main():
        store, bridge = MemoryRunStore(), MemoryStreamBridge()
        gate = asyncio.Event()

        class _SlowGraph(_FakeGraph):
            async def astream(self, graph_input, config=None, stream_mode=None):
                yield "updates", {"step": 1}
                await gate.wait()  # висим до отмены
                yield "updates", {"step": 2}

        async def fake_repo(url):
            return {"id": 1, "url": url}

        async def fake_sandbox(name):
            return _FakeSandbox()

        rt = Runtime(
            store=store,
            bridge=bridge,
            build_graph=lambda sb, m, checkpointer=None: _SlowGraph([], None),
            make_model=lambda **kw: object(),
            create_sandbox=fake_sandbox,
            get_or_create_repository=fake_repo,
        )
        result = await rt.submit(
            repo_url="u", commit_sha="c", llm_api_base="b", llm_api_key="k", llm_model="m"
        )
        run_id = result.run["id"]
        await asyncio.sleep(0.05)  # воркер дошёл до gate
        assert await rt.cancel(run_id) is CancelOutcome.cancelled
        final = await rt.wait(run_id)
        assert final["status"] == RunStatus.interrupted
        assert final["report"] is None

        # publish_end дошёл до подписчиков даже при отмене
        saw_end = False
        async for item in bridge.subscribe(run_id, heartbeat_interval=0.1):
            if item is END_SENTINEL:
                saw_end = True
                break
        assert saw_end

    asyncio.run(main())


# -- регрессии по итогам адверсариального ревью -------------------------------


def test_resume_updates_llm_credentials():
    async def main():
        store = MemoryRunStore()
        row, _ = await store.claim(**CLAIM)
        await store.start_run(row["id"], owner_worker_id="w1")
        await store.finish(row["id"], owner_worker_id="w1", status=RunStatus.failed, error="x")
        row2, disp = await store.claim(
            **{**CLAIM, "llm_api_base": "http://new", "llm_api_key": "fresh"}
        )
        assert disp == SubmitDisposition.resumed
        assert row2["llm_api_base"] == "http://new" and row2["llm_api_key"] == "fresh"

    asyncio.run(main())


def test_evict_is_identity_aware():
    async def main():
        store = MemoryRunStore()
        manager = RunManager(store, worker_id="w1")
        first = await manager.admit(**IDENTITY)
        old_record = manager.get_local(first.run["id"])
        old_record.status = RunStatus.failed
        await store.start_run(first.run["id"], owner_worker_id="w1")
        await store.finish(
            first.run["id"], owner_worker_id="w1", status=RunStatus.failed, error="x"
        )
        manager.evict_later(old_record, delay=0.01)

        second = await manager.admit(**IDENTITY)  # resume: новая запись, тот же id
        assert second.disposition == SubmitDisposition.resumed
        new_record = manager.get_local(second.run["id"])
        assert new_record is not old_record
        await asyncio.sleep(0.05)  # старый evict сработал
        assert manager.get_local(second.run["id"]) is new_record  # живая не снесена

    asyncio.run(main())


def test_attached_for_active_local_run():
    async def main():
        store = MemoryRunStore()
        manager = RunManager(store, worker_id="w1")
        first = await manager.admit(**IDENTITY)
        assert first.disposition == SubmitDisposition.created
        again = await manager.admit(**IDENTITY)
        assert again.disposition == SubmitDisposition.attached
        assert again.run["id"] == first.run["id"]

    asyncio.run(main())


def test_bridge_delayed_cleanup_spares_new_incarnation():
    async def main():
        bridge = MemoryStreamBridge()
        await bridge.publish(1, "updates", {"old": 1})
        old_cleanup = asyncio.create_task(bridge.cleanup(1, delay=0.03))
        await asyncio.sleep(0.01)
        await bridge.cleanup(1)  # resume: немедленный сброс
        await bridge.publish(1, "updates", {"new": 1})  # новая инкарнация
        await old_cleanup  # отложенная уборка старой не должна снести новую
        assert 1 in bridge._streams
        assert bridge._streams[1].events[0].data == {"new": 1}

    asyncio.run(main())


def test_cancel_during_finalize_still_publishes_end():
    async def main():
        store, bridge = MemoryRunStore(), MemoryStreamBridge()
        release = asyncio.Event()

        class _SlowCloseSandbox(_FakeSandbox):
            async def close(self):
                await release.wait()  # финализация висит на закрытии песочницы

        class _FailingGraph(_FakeGraph):
            async def astream(self, graph_input, config=None, stream_mode=None):
                raise RuntimeError("boom")
                yield  # pragma: no cover

        async def fake_repo(url):
            return {"id": 1, "url": url}

        async def fake_sandbox(name):
            return _SlowCloseSandbox()

        rt = Runtime(
            store=store,
            bridge=bridge,
            build_graph=lambda sb, m, checkpointer=None: _FailingGraph([], None),
            make_model=lambda **kw: object(),
            create_sandbox=fake_sandbox,
            get_or_create_repository=fake_repo,
        )
        result = await rt.submit(
            repo_url="u", commit_sha="c", llm_api_base="b", llm_api_key="k", llm_model="m"
        )
        run_id = result.run["id"]
        record = rt._manager.get_local(run_id)
        await asyncio.sleep(0.05)
        assert record.finalizing  # воркер застрял в финализации
        record.task.cancel()  # поздняя отмена (аналог shutdown)
        await asyncio.sleep(0.01)
        release.set()
        final = await rt.wait(run_id)
        assert final["status"] == RunStatus.failed  # финализация дошла до конца

        saw_end = False
        async for item in bridge.subscribe(run_id, heartbeat_interval=0.1):
            if item is END_SENTINEL:
                saw_end = True
                break
        assert saw_end  # publish_end пережил позднюю отмену

    asyncio.run(main())


def test_runtime_subscribe_terminal_run_ends_immediately():
    async def main():
        store, bridge = MemoryRunStore(), MemoryStreamBridge()
        rt = _make_runtime(store, bridge, report={"ok": 1})
        result = await rt.submit(
            repo_url="u", commit_sha="c", llm_api_base="b", llm_api_key="k", llm_model="m"
        )
        await rt.wait(result.run["id"])
        await bridge.cleanup(result.run["id"])  # стрим уже убран
        items = []
        async for item in rt.subscribe(result.run["id"]):
            items.append(item)
            break
        assert items == [END_SENTINEL]  # не вечные heartbeat'ы

    asyncio.run(main())
