"""RunManager — control plane: admission, lease+heartbeat, отмена, сироты."""

from __future__ import annotations

import asyncio
import socket
import time
import uuid
from typing import Any

from core.ports import RunStore
from core.runtime.schemas import (
    ACTIVE_STATUSES,
    ORPHAN_ERROR,
    STOP_REASON_ORPHAN,
    STOP_REASON_SHUTDOWN,
    CancelOutcome,
    ConflictError,
    RunRecord,
    RunStartOutcome,
    RunStartupError,
    RunStatus,
    SubmitDisposition,
    SubmitResult,
)
from pkg.logger import get_logger

log = get_logger(__name__)


def _generate_worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


class RunManager:
    def __init__(
        self,
        store: RunStore,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 30,
        grace_seconds: int = 10,
    ) -> None:
        self._store = store
        self.worker_id = worker_id or _generate_worker_id()
        self._lease_seconds = lease_seconds
        self._grace_seconds = grace_seconds
        self._runs: dict[int, RunRecord] = {}
        self._identity: dict[tuple[int, str, str], int] = {}
        self._lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task | None = None
        self._orphan_task: asyncio.Task | None = None
        self._evict_tasks: set[asyncio.Task] = set()
        self._shutting_down = False

    # -- admission -----------------------------------------------------------

    async def admit(self, **claim_kwargs: Any) -> SubmitResult:
        """Единственная дверь к созданию/возобновлению рана."""
        identity = (
            claim_kwargs["repository_id"],
            claim_kwargs["commit_sha"],
            claim_kwargs["llm_model"],
        )
        async with self._lock:
            local_id = self._identity.get(identity)
            local = self._runs.get(local_id) if local_id is not None else None
            if (
                local is not None
                and local.status in ACTIVE_STATUSES
                and not local.finalizing
                and not local.abort_event.is_set()
            ):
                row = await self._store.get(local.run_id)
                if row is not None and row["status"] in ACTIVE_STATUSES:
                    return SubmitResult(run=row, disposition=SubmitDisposition.attached)

            if local is not None and local.task is not None and not local.task.done():
                await asyncio.wait([local.task])

            row, disposition = await self._store.claim(
                owner_worker_id=self.worker_id,
                lease_seconds=self._lease_seconds,
                grace_seconds=self._grace_seconds,
                **claim_kwargs,
            )
            run_id = row["id"]

            if disposition == SubmitDisposition.already_succeeded:
                return SubmitResult(run=row, disposition=disposition)

            record = RunRecord(run_id=run_id, status=RunStatus.pending)
            record.lease_deadline = time.monotonic() + self._lease_seconds
            self._runs[run_id] = record
            self._identity[identity] = run_id
            return SubmitResult(run=row, disposition=disposition)

    def attach(self, run_id: int, task: asyncio.Task) -> None:
        record = self._runs.get(run_id)
        if record is not None:
            record.task = task

    def get_local(self, run_id: int) -> RunRecord | None:
        return self._runs.get(run_id)

    # -- startup barrier -----------------------------------------------------

    async def try_start(self, run_id: int) -> RunStartOutcome:
        record = self._runs.get(run_id)
        if record is None:
            raise RunStartupError(f"run {run_id} is not registered in this process")
        if record.abort_event.is_set() or record.status != RunStatus.pending:
            return RunStartOutcome.cancelled
        started = await self._store.start_run(run_id, owner_worker_id=self.worker_id)
        if not started:
            record.status = RunStatus.interrupted
            record.abort_event.set()
            return RunStartOutcome.cancelled
        if record.abort_event.is_set():
            await self._store.finish(
                run_id,
                owner_worker_id=self.worker_id,
                status=RunStatus.interrupted,
                stop_reason="cancelled_before_start",
            )
            record.status = RunStatus.interrupted
            return RunStartOutcome.cancelled
        record.status = RunStatus.running
        return RunStartOutcome.started

    # -- fence ---------------------------------------------------------------

    def mark_ownership_lost(self, run_id: int) -> None:
        record = self._runs.get(run_id)
        if record is None or record.ownership_lost:
            return
        record.ownership_lost = True
        record.status = RunStatus.failed
        record.abort_event.set()
        log.error("lease ownership lost; fencing run", run_id=run_id)
        if (
            record.task is not None
            and record.task is not asyncio.current_task()
            and not record.finalizing
        ):
            record.task.cancel()

    # -- cancel --------------------------------------------------------------

    async def cancel(self, run_id: int) -> CancelOutcome:
        record = self._runs.get(run_id)
        if record is not None:
            if record.finalizing or record.status not in ACTIVE_STATUSES:
                return CancelOutcome.not_cancellable
            await self._store.request_cancel(run_id)
            if record.finalizing or record.status not in ACTIVE_STATUSES:
                return CancelOutcome.not_cancellable
            record.abort_event.set()
            if record.status == RunStatus.running and record.task is not None:
                record.task.cancel()
            record.status = RunStatus.interrupted
            return CancelOutcome.cancelled

        row = await self._store.get(run_id)
        if row is None:
            return CancelOutcome.not_found
        if row["status"] not in ACTIVE_STATUSES:
            return CancelOutcome.not_cancellable
        taken = await self._store.claim_for_takeover(
            run_id,
            grace_seconds=self._grace_seconds,
            error="Cancelled while owner was unreachable.",
            stop_reason=STOP_REASON_ORPHAN,
        )
        if taken:
            return CancelOutcome.taken_over
        row = await self._store.get(run_id)
        if row is None or row["status"] not in ACTIVE_STATUSES:
            return CancelOutcome.not_cancellable
        if await self._store.request_cancel(run_id):
            return CancelOutcome.requested
        return CancelOutcome.not_cancellable

    # -- heartbeat -----------------------------------------------------------

    async def start(self) -> None:
        await self.reconcile_orphans()
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._heartbeat_task.set_name("git-agent-runtime-heartbeat")

    async def _heartbeat_loop(self) -> None:
        tick = max(1, self._lease_seconds // 3)
        ticks = 0
        while True:
            await asyncio.sleep(tick)
            ticks += 1
            try:
                await self._renew_leases()
            except Exception:
                log.exception("heartbeat pass failed")
            if ticks % 3 == 0:
                self._schedule_orphan_reconciliation()

    async def _renew_leases(self) -> None:
        to_cancel: list[int] = []
        for run_id, record in list(self._runs.items()):
            if record.ownership_lost:
                continue
            if record.status not in ACTIVE_STATUSES and not record.finalizing:
                continue
            if record.task is not None and record.task.done():
                continue
            deadline = record.lease_deadline
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                self.mark_ownership_lost(run_id)
                continue
            remaining = None if deadline is None else deadline - now
            try:
                if remaining is not None:
                    async with asyncio.timeout(remaining):
                        renewal = await self._store.renew_lease(
                            run_id,
                            owner_worker_id=self.worker_id,
                            lease_seconds=self._lease_seconds,
                        )
                else:
                    renewal = await self._store.renew_lease(
                        run_id,
                        owner_worker_id=self.worker_id,
                        lease_seconds=self._lease_seconds,
                    )
            except TimeoutError:
                self.mark_ownership_lost(run_id)
                continue
            except Exception:
                if deadline is not None and time.monotonic() >= deadline:
                    self.mark_ownership_lost(run_id)
                else:
                    log.warning("lease renewal error; retrying next tick", run_id=run_id)
                continue
            if not renewal.renewed:
                self.mark_ownership_lost(run_id)
                continue
            if deadline is not None and time.monotonic() >= deadline:
                self.mark_ownership_lost(run_id)
                continue
            record.lease_deadline = time.monotonic() + self._lease_seconds
            if renewal.cancel_requested:
                to_cancel.append(run_id)
        for run_id in to_cancel:
            self._signal_local_cancel(run_id)

    def _signal_local_cancel(self, run_id: int) -> None:
        record = self._runs.get(run_id)
        if record is None or record.status not in ACTIVE_STATUSES:
            return
        log.info("durable cancel observed via heartbeat", run_id=run_id)
        record.abort_event.set()
        if record.status == RunStatus.running and record.task is not None:
            record.task.cancel()
        # статус не трогаем — владеющий таск финализирует сам

    # -- orphan recovery -----------------------------------------------------

    def _schedule_orphan_reconciliation(self) -> None:
        if self._orphan_task is not None and not self._orphan_task.done():
            return
        self._orphan_task = asyncio.create_task(self._reconcile_safely())

    async def _reconcile_safely(self) -> None:
        try:
            await self.reconcile_orphans()
        except Exception:
            log.exception("orphan reconciliation failed")

    async def reconcile_orphans(self) -> list[int]:
        recovered: list[int] = []
        for row in await self._store.list_expired(grace_seconds=self._grace_seconds):
            run_id = row["id"]
            local = self._runs.get(run_id)
            if local is not None and local.status in ACTIVE_STATUSES and not local.ownership_lost:
                continue
            if await self._store.claim_for_takeover(
                run_id,
                grace_seconds=self._grace_seconds,
                error=ORPHAN_ERROR,
                stop_reason=STOP_REASON_ORPHAN,
            ):
                recovered.append(run_id)
                log.warning("orphaned run recovered", run_id=run_id)
        return recovered

    # -- lifecycle -----------------------------------------------------------

    def evict_later(self, record: RunRecord, *, delay: float = 300) -> None:
        async def _evict() -> None:
            await asyncio.sleep(delay)
            if self._runs.get(record.run_id) is record:
                self._runs.pop(record.run_id, None)

        task = asyncio.create_task(_evict())
        self._evict_tasks.add(task)
        task.add_done_callback(self._evict_tasks.discard)

    async def shutdown(self, *, timeout: float = 10.0) -> None:
        self._shutting_down = True
        inflight = [
            r
            for r in self._runs.values()
            if r.task is not None
            and not r.task.done()
            and (r.status in ACTIVE_STATUSES or r.finalizing)
        ]
        for record in inflight:
            record.abort_event.set()
            if not record.finalizing:
                record.task.cancel()
        for t in (self._heartbeat_task, self._orphan_task):
            if t is not None:
                t.cancel()
        if inflight:
            done, _pending = await asyncio.wait([r.task for r in inflight], timeout=timeout)
            for task in done:
                if not task.cancelled() and task.exception() is not None:
                    log.warning(
                        "run task ended with error during shutdown", error=str(task.exception())
                    )
            for record in inflight:
                if record.ownership_lost:
                    continue
                row = await self._store.get(record.run_id)
                if row is not None and row["status"] in ("pending", "running"):
                    await self._store.finish(
                        record.run_id,
                        owner_worker_id=self.worker_id,
                        status=RunStatus.interrupted,
                        error="Process shutting down.",
                        stop_reason=STOP_REASON_SHUTDOWN,
                    )
        for task in list(self._evict_tasks):
            task.cancel()


__all__ = ["ConflictError", "RunManager"]
