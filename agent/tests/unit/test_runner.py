"""Раннер герметично: парсер События, crypto, клейм/форвард/дедуп/слоты/idle."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from core.runner.crypto import decrypt, encrypt
from core.runner.events import Event, parse_event
from core.runner.ports import ClaimResult, SandboxNotProvisionedError
from core.runner.service import RunnerService

WIRE = {
    "eventId": 7,
    "instanceId": 3,
    "threadId": "inst-3",
    "repositoryId": 5,
    "provider": "github",
    "action": "push",
    "commitSha": "abc123",
    "ref": "refs/heads/main",
    "dedupKey": "abc123",
}


def test_parse_event_roundtrip():
    event = parse_event(WIRE)
    assert event == Event(
        event_id=7,
        instance_id=3,
        thread_id="inst-3",
        repository_id=5,
        provider="github",
        action="push",
        dedup_key="abc123",
        commit_sha="abc123",
        ref="refs/heads/main",
    )
    assert parse_event(event.to_wire()) == event


def test_parse_event_optional_and_bad():
    minimal = {k: v for k, v in WIRE.items() if k not in ("commitSha", "ref")}
    event = parse_event(minimal)
    assert event.commit_sha is None and event.ref is None
    with pytest.raises(ValueError):
        parse_event({"eventId": 1})


def test_crypto_roundtrip():
    key = (b"k" * 32).hex()
    blob = encrypt("s3cret", key, nonce=os.urandom(12))
    assert decrypt(blob, key) == "s3cret"
    assert decrypt(None, key) is None
    with pytest.raises(ValueError):
        decrypt(blob, "")


class MemStore:
    """In-memory зеркало CAS-семантики hub.agent_instances/instance_events."""

    def __init__(self):
        self.instances: dict[int, dict[str, Any]] = {}
        self.addresses: dict[int, str] = {}
        self.journal: dict[tuple[int, str], bool] = {}  # -> processed?
        self.contexts: dict[int, dict[str, Any]] = {}

    async def register_runner(self, *, name: str, address: str, slots: int) -> int:
        return 1

    async def heartbeat_runner(self, runner_id: int) -> None:
        pass

    async def claim_instance(self, instance_id: int, *, runner_id: int) -> ClaimResult:
        inst = self.instances.get(instance_id)
        if inst is None:
            return ClaimResult("missing")
        if inst["status"] == "down" or inst["runner_id"] == runner_id:
            inst.update(status="running", runner_id=runner_id)
            return ClaimResult("claimed")
        return ClaimResult("held_by_other", holder_address=self.addresses.get(inst["runner_id"]))

    async def release_instance(self, instance_id: int, *, runner_id: int) -> bool:
        inst = self.instances.get(instance_id)
        if inst and inst["status"] == "running" and inst["runner_id"] == runner_id:
            inst.update(status="down", runner_id=None)
            return True
        return False

    async def begin_event(self, event: Event) -> bool:
        key = (event.instance_id, event.dedup_key)
        if self.journal.get(key):
            return False
        self.journal[key] = False
        return True

    async def mark_processed(self, instance_id: int, dedup_key: str) -> None:
        self.journal[(instance_id, dedup_key)] = True

    async def load_context(self, instance_id: int) -> dict[str, Any] | None:
        return self.contexts.get(instance_id)

    async def add_report(self, instance_id, *, event_id, summary) -> int:
        return 1

    async def add_finding(self, instance_id, finding) -> None:
        pass


class FakeHub:
    def __init__(self, forward_ok: bool = True):
        self.forward_ok = forward_ok
        self.forwarded: list[tuple[str, Event]] = []

    async def register(self, **kwargs):
        pass

    async def heartbeat(self, **kwargs):
        pass

    async def forward_event(self, address: str, event: Event) -> bool:
        self.forwarded.append((address, event))
        return self.forward_ok


class FakeExecutor:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.processed: list[Event] = []

    async def process_event(self, ctx, event):
        if self.error:
            raise self.error
        self.processed.append(event)


def make_service(store, hub=None, executor=None, *, slots=2, idle=900.0) -> RunnerService:
    return RunnerService(
        store=store,
        hub=hub or FakeHub(),
        executor=executor or FakeExecutor(),
        name="r1",
        address="http://r1:8081",
        slots=slots,
        idle_timeout_seconds=idle,
    )


def seed(store: MemStore, instance_id=3, status="down", runner_id=None):
    store.instances[instance_id] = {"status": status, "runner_id": runner_id}
    store.contexts[instance_id] = {"id": instance_id, "thread_id": f"inst-{instance_id}"}


async def started(service: RunnerService) -> RunnerService:
    await service.start()
    return service


def test_event_processed_and_marked():
    async def run():
        store = MemStore()
        seed(store)
        executor = FakeExecutor()
        service = await started(make_service(store, executor=executor))
        outcome = await service.handle_event(parse_event(WIRE))
        assert outcome == "processed"
        assert [e.event_id for e in executor.processed] == [7]
        assert store.journal[(3, "abc123")] is True
        assert store.instances[3] == {"status": "running", "runner_id": 1}
        assert service.busy == 1

    asyncio.run(run())


def test_duplicate_event_skipped():
    async def run():
        store = MemStore()
        seed(store)
        executor = FakeExecutor()
        service = await started(make_service(store, executor=executor))
        event = parse_event(WIRE)
        assert await service.handle_event(event) == "processed"
        assert await service.handle_event(event) == "duplicate"
        assert len(executor.processed) == 1

    asyncio.run(run())


def test_unprocessed_republish_is_reprocessed():
    async def run():
        store = MemStore()
        seed(store)
        error = FakeExecutor(error=RuntimeError("boom"))
        service = await started(make_service(store, executor=error))
        event = parse_event(WIRE)
        with pytest.raises(RuntimeError):
            await service.handle_event(event)
        assert store.journal[(3, "abc123")] is False  # processed_at не встал
        # ре-публикация: другой (здоровый) executor доисполняет то же Событие
        error.error = None
        assert await service.handle_event(event) == "processed"
        assert store.journal[(3, "abc123")] is True

    asyncio.run(run())


def test_sandbox_not_provisioned_drops_without_processed():
    async def run():
        store = MemStore()
        seed(store)
        executor = FakeExecutor(error=SandboxNotProvisionedError("instance 3: sandbox not provisioned"))
        service = await started(make_service(store, executor=executor))
        event = parse_event(WIRE)
        assert await service.handle_event(event) == "dropped"
        assert store.journal[(3, "abc123")] is False  # ре-публикация доисполнит
        # юзер создал песочницу — то же Событие обрабатывается
        executor.error = None
        assert await service.handle_event(event) == "processed"

    asyncio.run(run())


def test_forward_to_holder():
    async def run():
        store = MemStore()
        seed(store, status="running", runner_id=2)
        store.addresses[2] = "http://r2:8081"
        hub = FakeHub()
        service = await started(make_service(store, hub=hub))
        assert await service.handle_event(parse_event(WIRE)) == "forwarded"
        assert hub.forwarded[0][0] == "http://r2:8081"
        assert service.busy == 0
        hub.forward_ok = False
        assert await service.handle_event(parse_event(WIRE)) == "dropped"

    asyncio.run(run())


def test_slots_block_until_free():
    async def run():
        store = MemStore()
        seed(store, instance_id=3)
        seed(store, instance_id=4)
        service = await started(make_service(store, slots=1))
        assert await service.raise_instance(3)
        second = asyncio.ensure_future(service.raise_instance(4))
        await asyncio.sleep(0.01)
        assert not second.done()  # слот занят — подъём ждёт
        await service.stop_instance(3)
        assert await asyncio.wait_for(second, 1)
        assert store.instances[3]["status"] == "down"
        assert store.instances[4]["status"] == "running"

    asyncio.run(run())


def test_slot_waiter_does_not_block_raised_instances():
    """Ожидающий слота подъём не должен стопорить чат/События к уже поднятым."""

    async def run():
        store = MemStore()
        seed(store, instance_id=3)
        seed(store, instance_id=4)
        service = await started(make_service(store, slots=1))
        assert await service.raise_instance(3)
        waiter = asyncio.ensure_future(service.raise_instance(4))
        await asyncio.sleep(0.01)
        # Событие к поднятому Экземпляру проходит, пока waiter висит на слоте
        assert await asyncio.wait_for(service.handle_event(parse_event(WIRE)), 0.5) == "processed"
        await service.stop_instance(3)
        assert await asyncio.wait_for(waiter, 1)

    asyncio.run(run())


def test_idle_reap_releases_instance():
    async def run():
        store = MemStore()
        seed(store)
        service = await started(make_service(store, idle=0.0))
        assert await service.raise_instance(3)
        service._instances[3].last_activity -= 1  # активность в прошлом
        await service.reap_idle()
        assert service.busy == 0
        assert store.instances[3] == {"status": "down", "runner_id": None}

    asyncio.run(run())


def test_missing_instance_dropped():
    async def run():
        store = MemStore()
        service = await started(make_service(store))
        assert await service.handle_event(parse_event(WIRE)) == "dropped"
        assert service.busy == 0

    asyncio.run(run())
