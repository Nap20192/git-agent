"""Раннер герметично: парсер События, crypto, клейм/форвард/дедуп/слоты/idle."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from structlog.contextvars import get_contextvars

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
    "traceId": "0123456789abcdef0123456789abcdef",
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
        trace_id="0123456789abcdef0123456789abcdef",
    )
    assert parse_event(event.to_wire()) == event


def test_parse_event_optional_and_bad():
    minimal = {k: v for k, v in WIRE.items() if k not in ("commitSha", "ref")}
    event = parse_event(minimal)
    assert event.commit_sha is None and event.ref is None
    with pytest.raises(ValueError):
        parse_event({"eventId": 1})


def test_event_prompt_full_scan():
    from core.runner.executor import _event_prompt

    ctx = {"owner": "acme", "name": "repo", "prompt": "Сборка: смотри в оба"}
    full = _event_prompt(
        ctx, parse_event({**WIRE, "action": "full_scan", "dedupKey": "full-abc123"})
    )
    for marker in (
        "FULL security audit",
        "plan the areas",
        "subagent",
        "task",
        "report_finding",
        "write_report",
    ):
        assert marker in full
    assert "Сборка: смотри в оба" in full  # промпт Сборки остаётся
    assert "FULL security audit" not in _event_prompt(ctx, parse_event(WIRE))


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
        self.activity: list[tuple[int, int | None, int, dict[str, Any]]] = []
        self.activity_traces: list[str] = []

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

    async def peek_holder(self, instance_id: int, *, runner_id: int) -> ClaimResult:
        inst = self.instances.get(instance_id)
        if inst is None:
            return ClaimResult("missing")
        if inst["status"] != "running":
            return ClaimResult("free")
        if inst["runner_id"] == runner_id:
            return ClaimResult("held_by_self")
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

    async def add_report(self, instance_id, *, event_id, summary, structured=None) -> int:
        return 1

    async def add_finding(self, instance_id, finding, *, event_id=None) -> None:
        pass

    async def add_activity(self, instance_id, *, event_id, seq, frame, trace_id="") -> None:
        self.activity.append((instance_id, event_id, seq, frame))
        self.activity_traces.append(trace_id)

    async def list_activity(self, instance_id, *, event_id=None, latest=False):
        rows = [r for r in self.activity if r[0] == instance_id]
        if latest:
            event_id = rows[-1][1] if rows else None
        return [frame for (_, eid, _, frame) in rows if eid == event_id]


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
        self.terminal_calls: list[tuple[str, str | None]] = []
        self.chunks: list[tuple[str, Any]] = []  # стрим-чанки хода для on_chunk
        self.contexts: list[dict[str, Any]] = []

    async def process_event(self, ctx, event, on_chunk=None):
        self.contexts.append(get_contextvars())  # лог-контекст хода (trace_id и др.)
        if self.error:
            raise self.error
        if on_chunk is not None:
            for mode, data in self.chunks:
                await on_chunk(mode, data)
        self.processed.append(event)

    async def terminal(self, ctx, command, cwd=None):
        self.terminal_calls.append((command, cwd))
        if command.startswith("cd "):
            return "", 0, command.removeprefix("cd ")
        return "out", 0, cwd or "/repo"


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


def test_trace_id_from_message_binds_turn_context():
    """traceId Rabbit-сообщения → contextvars хода, activity-кадры и hub.activity.trace_id."""

    async def run():
        store = MemStore()
        seed(store)
        executor = FakeExecutor()
        service = await started(make_service(store, executor=executor))
        await service.handle_event(parse_event(WIRE))
        trace_id = WIRE["traceId"]
        assert executor.contexts[0]["trace_id"] == trace_id
        assert executor.contexts[0]["event_id"] == 7
        assert store.activity_traces and set(store.activity_traces) == {trace_id}
        assert all(frame["traceId"] == trace_id for (_, _, _, frame) in store.activity)

        # сообщение без traceId (до миграции 004) — ход получает свежий 32-hex id
        await service.handle_event(
            parse_event({**WIRE, "eventId": 8, "dedupKey": "def", "traceId": ""})
        )
        generated = executor.contexts[1]["trace_id"]
        assert generated != trace_id and len(generated) == 32 and int(generated, 16) >= 0

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
        executor = FakeExecutor(
            error=SandboxNotProvisionedError("instance 3: sandbox not provisioned")
        )
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


def test_stop_cancels_running_turn():
    """Стоп посреди хода: ход отменён, processed_at NULL, слот свободен, экземпляр down."""

    async def run():
        store = MemStore()
        seed(store)
        turn_started = asyncio.Event()

        class BlockingExecutor(FakeExecutor):
            async def process_event(self, ctx, event, on_chunk=None):
                turn_started.set()
                await asyncio.Event().wait()  # висим до отмены

        service = await started(make_service(store, executor=BlockingExecutor()))
        handling = asyncio.ensure_future(service.handle_event(parse_event(WIRE)))
        await asyncio.wait_for(turn_started.wait(), 1)
        assert await service.stop_instance(3)
        assert await asyncio.wait_for(handling, 1) == "cancelled"
        assert store.journal[(3, "abc123")] is False  # Событие осталось незавершённым
        assert store.instances[3] == {"status": "down", "runner_id": None}
        assert service.busy == 0
        # слот свободен — новый подъём проходит
        assert await service.raise_instance(3) == "running"

    asyncio.run(run())


def test_terminal_does_not_wait_for_running_turn():
    """Ход висит (Лид думает) — команда консоли выполняется сразу, не ждёт lock хода."""

    async def run():
        store = MemStore()
        seed(store)
        turn_started = asyncio.Event()

        class BlockingExecutor(FakeExecutor):
            async def process_event(self, ctx, event, on_chunk=None):
                turn_started.set()
                await asyncio.Event().wait()

        service = await started(make_service(store, executor=BlockingExecutor()))
        handling = asyncio.ensure_future(service.handle_event(parse_event(WIRE)))
        await asyncio.wait_for(turn_started.wait(), 1)
        assert await asyncio.wait_for(service.terminal(3, "ls"), 0.5) == ("out", 0, "/repo")
        # консоль не опускает Экземпляр из-под хода и не завершает его
        assert not handling.done()
        assert await service.stop_instance(3)
        assert await asyncio.wait_for(handling, 1) == "cancelled"

    asyncio.run(run())


def test_raise_queued_when_slots_busy(monkeypatch):
    """raise при занятых слотах — мгновенный queued; слот освободился — running фоном."""

    async def run():
        from core.runner import service as service_mod

        monkeypatch.setattr(service_mod, "RAISE_WAIT_SECONDS", 0.01)
        store = MemStore()
        seed(store, instance_id=3)
        seed(store, instance_id=4)
        service = await started(make_service(store, slots=1))
        assert await service.raise_instance(3) == "running"
        assert await service.raise_instance(4) == "queued"
        assert store.instances[4]["status"] == "down"  # ещё ждёт слот
        await service.stop_instance(3)
        for _ in range(100):
            if store.instances[4]["status"] == "running":
                break
            await asyncio.sleep(0.01)
        assert store.instances[4] == {"status": "running", "runner_id": 1}
        assert service.busy == 1

    asyncio.run(run())


def test_forward_does_not_wait_for_slot():
    """Чужое Событие форвардится сразу, даже когда все слоты заняты."""

    async def run():
        store = MemStore()
        seed(store, instance_id=3)
        seed(store, instance_id=4, status="running", runner_id=2)
        store.addresses[2] = "http://r2:8082"
        hub = FakeHub()
        service = await started(make_service(store, hub=hub, slots=1))
        assert await service.raise_instance(3)  # единственный слот занят
        event = parse_event({**WIRE, "instanceId": 4})
        assert await asyncio.wait_for(service.handle_event(event), 0.5) == "forwarded"
        assert hub.forwarded[0][0] == "http://r2:8082"

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


def test_terminal_carries_cwd_between_commands():
    async def run():
        store = MemStore()
        seed(store)
        executor = FakeExecutor()
        service = await started(make_service(store, executor=executor))
        # первый вызов поднимает Экземпляр, cwd ещё не задана
        assert await service.terminal(3, "ls") == ("out", 0, "/repo")
        assert await service.terminal(3, "cd /repo/sub") == ("", 0, "/repo/sub")
        await service.terminal(3, "ls")
        assert executor.terminal_calls == [
            ("ls", None),
            ("cd /repo/sub", "/repo"),
            ("ls", "/repo/sub"),
        ]
        # stop сбрасывает консоль вместе с Экземпляром
        await service.stop_instance(3)
        await service.terminal(3, "ls")
        assert executor.terminal_calls[-1] == ("ls", None)

    asyncio.run(run())


SCOPE_WIRE = {
    **WIRE,
    "beforeSha": "bbb111",
    "baseSha": "base22",
    "headSha": "head33",
    "prNumber": 42,
    "prTitle": "Add login",
    "prBody": "Adds password login",
    "changedFiles": ["a.py", "b/c.go"],
}


def test_parse_event_scope_fields_optional_and_roundtrip():
    old = parse_event(WIRE)  # сообщение без полей скоупа — как прежде
    assert (old.before_sha, old.base_sha, old.head_sha, old.pr_number) == (None,) * 4
    assert old.changed_files == () and "beforeSha" not in old.to_wire()
    event = parse_event(SCOPE_WIRE)
    assert (event.before_sha, event.base_sha, event.head_sha) == ("bbb111", "base22", "head33")
    assert (event.pr_number, event.pr_title, event.pr_body) == (
        42,
        "Add login",
        "Adds password login",
    )
    assert event.changed_files == ("a.py", "b/c.go")
    assert parse_event(event.to_wire()) == event
    # нулевой sha провайдера (первый пуш ветки) — отсутствие значения
    assert parse_event({**WIRE, "beforeSha": "0" * 40}).before_sha is None
    with pytest.raises(ValueError):
        parse_event({**WIRE, "changedFiles": "a.py"})


def test_has_code_target_by_action_and_commit():
    assert parse_event(WIRE).has_code_target  # push с коммитом
    no_commit = {k: v for k, v in WIRE.items() if k != "commitSha"}
    assert not parse_event({**no_commit, "action": "ping"}).has_code_target
    assert not parse_event({**no_commit, "action": "push"}).has_code_target
    assert parse_event({**no_commit, "action": "full_scan"}).has_code_target
    assert parse_event({**no_commit, "action": "manual"}).has_code_target
    assert parse_event({**no_commit, "action": "pull_request", "headSha": "h"}).has_code_target


def test_event_prompt_by_action():
    from core.runner.executor import _event_prompt

    ctx = {"owner": "acme", "name": "repo"}
    push = _event_prompt(ctx, parse_event(SCOPE_WIRE))
    for marker in (
        "bbb111..abc123",
        "git_diff(ref='abc123', base='bbb111', stat=true)",
        "git log",
        "ONLY the touched code",
        "Do not scan the whole",
        "a.py, b/c.go",
        "report_finding",
        "write_report",
    ):
        assert marker in push, marker
    first_push = _event_prompt(ctx, parse_event(WIRE))
    assert (
        "force-push" in first_push
        and "HEAD~1" in first_push
        and "git_diff(ref='abc123', stat=true)" in first_push
    )
    pr = _event_prompt(ctx, parse_event({**SCOPE_WIRE, "action": "pull_request"}), merge_base="mb0")
    for marker in (
        "PR #42: Add login",
        "Adds password login",
        "mb0...head33",
        "git_diff(ref='head33', base='mb0', stat=true)",
        "REVIEW MODE",
        "attack surface",
        "PR review",
        "do not scan",
    ):
        assert marker in pr, marker
    pr_no_mb = _event_prompt(ctx, parse_event({**SCOPE_WIRE, "action": "merge_request"}))
    assert "base22...head33" in pr_no_mb and "PR base" in pr_no_mb
    manual = _event_prompt(ctx, parse_event({**WIRE, "action": "manual"}))
    assert "Manual run" in manual and "previous commit" in manual and "do not scan" in manual
    full = _event_prompt(ctx, parse_event({**WIRE, "action": "full_scan"}))
    assert "FULL security audit" in full and "scan the whole" not in full
    long_body = _event_prompt(
        ctx, parse_event({**SCOPE_WIRE, "action": "pull_request", "prBody": "x" * 5000})
    )
    assert "[truncated]" in long_body and "x" * 2001 not in long_body


def test_event_without_commit_skipped_and_marked_processed():
    """ping/issues/comments: ход не поднимается, Экземпляр не клеймится, processed_at стоит."""

    async def run():
        store = MemStore()
        seed(store)
        executor = FakeExecutor()
        service = await started(make_service(store, executor=executor))
        wire = {k: v for k, v in WIRE.items() if k != "commitSha"}
        event = parse_event({**wire, "action": "ping", "dedupKey": "ping-1"})
        assert await service.handle_event(event) == "skipped_no_commit"
        assert executor.processed == []
        assert store.journal[(3, "ping-1")] is True  # processed_at — ре-публикации не будет
        assert store.instances[3]["status"] == "down" and service.busy == 0
        assert await service.handle_event(event) == "skipped_no_commit"  # идемпотентно

    asyncio.run(run())
