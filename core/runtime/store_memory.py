"""In-memory RunStore — тестовая ступень лестницы и исполняемая спецификация порта."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

from core.runtime.schemas import (
    ACTIVE_STATUSES,
    ConflictError,
    LeaseRenewal,
    RunStatus,
    StatusFinalization,
    SubmitDisposition,
    assert_transition,
)


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[int, dict[str, Any]] = {}
        self._identity: dict[tuple[int, str, str], int] = {}
        self._events: dict[int, list[dict[str, Any]]] = {}
        self._run_ids = itertools.count(1)
        self._event_ids = itertools.count(1)

    def _active(self, row: dict[str, Any]) -> bool:
        return row["status"] in ACTIVE_STATUSES

    @staticmethod
    def _lease_valid(row: dict[str, Any], grace_seconds: int) -> bool:
        lease = row["lease_expires_at"]
        return lease is not None and lease >= _now() - timedelta(seconds=grace_seconds)

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
        key = (repository_id, commit_sha, llm_model)
        run_id = self._identity.get(key)
        if run_id is None:
            run_id = next(self._run_ids)
            row = {
                "id": run_id,
                "repository_id": repository_id,
                "commit_sha": commit_sha,
                "llm_api_base": llm_api_base,
                "llm_api_key": llm_api_key,
                "llm_model": llm_model,
                "status": RunStatus.pending,
                "error": None,
                "stop_reason": None,
                "report": None,
                "cancel_requested_at": None,
                "owner_worker_id": owner_worker_id,
                "lease_expires_at": _now() + timedelta(seconds=lease_seconds),
                "attempt": 1,
                "started_at": _now(),
                "finished_at": None,
                "updated_at": _now(),
            }
            self._runs[run_id] = row
            self._identity[key] = run_id
            return dict(row), SubmitDisposition.created

        row = self._runs[run_id]
        if row["status"] == RunStatus.succeeded:
            return dict(row), SubmitDisposition.already_succeeded
        if self._active(row) and self._lease_valid(row, grace_seconds):
            raise ConflictError(f"run {run_id} is active with a valid lease")
        if not self._active(row):
            assert_transition(RunStatus(row["status"]), RunStatus.pending, via_claim=True)
        row.update(
            status=RunStatus.pending,
            owner_worker_id=owner_worker_id,
            lease_expires_at=_now() + timedelta(seconds=lease_seconds),
            llm_api_base=llm_api_base,
            llm_api_key=llm_api_key,
            error=None,
            stop_reason=None,
            cancel_requested_at=None,
            report=None,
            attempt=row["attempt"] + 1,
            started_at=_now(),
            finished_at=None,
            updated_at=_now(),
        )
        return dict(row), SubmitDisposition.resumed

    async def get(self, run_id: int) -> dict[str, Any] | None:
        row = self._runs.get(run_id)
        return dict(row) if row else None

    async def set_limits(self, run_id: int, limits: dict[str, Any] | None) -> None:
        row = self._runs.get(run_id)
        if row is not None:
            row["limits"] = limits

    async def delete_run(self, run_id: int) -> bool:
        row = self._runs.get(run_id)
        if row is None:
            return False
        if row["status"] in ACTIVE_STATUSES:
            raise RuntimeError("cannot delete an active run; cancel it first")
        self._runs.pop(run_id, None)
        self._events.pop(run_id, None)
        for key, rid in list(self._identity.items()):
            if rid == run_id:
                self._identity.pop(key, None)
        return True

    async def start_run(self, run_id: int, *, owner_worker_id: str) -> bool:
        row = self._runs.get(run_id)
        if (
            row is None
            or row["status"] != RunStatus.pending
            or row["owner_worker_id"] != owner_worker_id
        ):
            return False
        assert_transition(RunStatus(row["status"]), RunStatus.running)
        row.update(status=RunStatus.running, updated_at=_now())
        return True

    async def renew_lease(
        self, run_id: int, *, owner_worker_id: str, lease_seconds: int
    ) -> LeaseRenewal:
        row = self._runs.get(run_id)
        if row is None or not self._active(row) or row["owner_worker_id"] != owner_worker_id:
            return LeaseRenewal(renewed=False)
        row.update(lease_expires_at=_now() + timedelta(seconds=lease_seconds), updated_at=_now())
        return LeaseRenewal(renewed=True, cancel_requested=row["cancel_requested_at"] is not None)

    async def request_cancel(self, run_id: int) -> bool:
        row = self._runs.get(run_id)
        if row is None or not self._active(row):
            return False
        if row["cancel_requested_at"] is None:
            row.update(cancel_requested_at=_now(), updated_at=_now())
        return True

    async def finalize_if_not_cancelled(
        self, run_id: int, *, owner_worker_id: str, report: dict[str, Any] | None
    ) -> StatusFinalization:
        row = self._runs.get(run_id)
        if (
            row is not None
            and row["status"] == RunStatus.running
            and row["owner_worker_id"] == owner_worker_id
            and row["cancel_requested_at"] is None
        ):
            assert_transition(RunStatus(row["status"]), RunStatus.succeeded)
            row.update(
                status=RunStatus.succeeded, report=report, finished_at=_now(), updated_at=_now()
            )
            return StatusFinalization(finalized=True)
        if row is not None and self._active(row) and row["cancel_requested_at"] is not None:
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
        row = self._runs.get(run_id)
        if row is None or not self._active(row) or row["owner_worker_id"] != owner_worker_id:
            return False
        assert_transition(RunStatus(row["status"]), RunStatus(status))
        row.update(
            status=RunStatus(status),
            error=error,
            stop_reason=stop_reason,
            finished_at=_now(),
            updated_at=_now(),
        )
        return True

    async def claim_for_takeover(
        self, run_id: int, *, grace_seconds: int, error: str, stop_reason: str
    ) -> bool:
        row = self._runs.get(run_id)
        if row is None or not self._active(row) or self._lease_valid(row, grace_seconds):
            return False
        assert_transition(RunStatus(row["status"]), RunStatus.failed)
        row.update(
            status=RunStatus.failed,
            error=error,
            stop_reason=stop_reason,
            owner_worker_id=None,
            finished_at=_now(),
            updated_at=_now(),
        )
        return True

    async def list_expired(self, *, grace_seconds: int) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self._runs.values()
            if self._active(row) and not self._lease_valid(row, grace_seconds)
        ]

    async def add_event(self, run_id: int, kind: str, payload: dict[str, Any]) -> None:
        self._events.setdefault(run_id, []).append(
            {
                "id": next(self._event_ids),
                "run_id": run_id,
                "kind": kind,
                "payload": payload,
                "created_at": _now(),
            }
        )

    async def list_events_after(
        self, run_id: int, after_id: int | None, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        events = self._events.get(run_id, [])
        if after_id is not None:
            events = [e for e in events if e["id"] > after_id]
        return [dict(e) for e in events[:limit]]
