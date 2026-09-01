"""Статусы, исходы и process-local записи рантайма Ранов."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    interrupted = "interrupted"


ACTIVE_STATUSES = frozenset({RunStatus.pending, RunStatus.running})
TERMINAL_STATUSES = frozenset({RunStatus.succeeded, RunStatus.failed, RunStatus.interrupted})

# Статусная машина (formal/RuntimeCore.lean::Step, адаптация — см. formal/MAPPING.md):
# succeeded — абсолютно поглощающий; failed|interrupted покидаются ТОЛЬКО через
# claim (resume = новая попытка того же ресурса, в модели — свежий admit, не Step).
LEGAL_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.pending: frozenset({RunStatus.running, RunStatus.interrupted, RunStatus.failed}),
    RunStatus.running: frozenset({RunStatus.succeeded, RunStatus.failed, RunStatus.interrupted}),
    RunStatus.succeeded: frozenset(),
    RunStatus.failed: frozenset({RunStatus.pending}),
    RunStatus.interrupted: frozenset({RunStatus.pending}),
}
_RESUME = {RunStatus.failed, RunStatus.interrupted}


def assert_transition(old: RunStatus, new: RunStatus, *, via_claim: bool = False) -> None:
    """Тripwire статусной машины (Lean: terminal_absorbing / step_target_sound)."""
    assert new in LEGAL_TRANSITIONS[old], f"illegal transition {old} -> {new}"
    if new is RunStatus.pending:
        assert via_claim and old in _RESUME, f"resume {old}->pending only via claim"


STOP_REASON_ORPHAN = "orphan_recovered"
STOP_REASON_CANCELLED = "cancelled"
STOP_REASON_SHUTDOWN = "shutting_down"
STOP_REASON_TURN = "turn_capped"
ORPHAN_ERROR = "Worker crashed or lease expired before the run finished."


class RunStartOutcome(StrEnum):
    started = "started"
    cancelled = "cancelled"


class SubmitDisposition(StrEnum):
    created = "created"
    resumed = "resumed"
    already_succeeded = "already_succeeded"
    # attached = активный ран уже идёт в этом процессе; вызывающий просто подписывается
    attached = "attached"


class CancelOutcome(StrEnum):
    cancelled = "cancelled"  # локальный ран, отменён немедленно
    requested = "requested"  # владелец жив в другом процессе, увидит по heartbeat
    taken_over = "taken_over"  # lease истёк, ран терминализирован нами
    not_cancellable = "not_cancellable"
    not_found = "not_found"


class ConflictError(Exception):
    """Активный ран с валидным lease уже существует (HTTP-слой отдаст 409)."""


class RunStartupError(RuntimeError):
    """try_start вызван для рана, неизвестного этому процессу."""


@dataclass(frozen=True)
class LeaseRenewal:
    renewed: bool
    cancel_requested: bool = False


@dataclass(frozen=True)
class StatusFinalization:
    finalized: bool
    cancelled: bool = False


@dataclass
class RunRecord:
    """Process-local живой хендл рана.

    ownership_lost — одноносторонний fence: после установки процесс не делает
    durable-записей по этому рану. lease_deadline (monotonic) двигается только
    после ПОДТВЕРЖДЁННОГО продления lease.
    """

    run_id: int
    status: RunStatus
    abort_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    ownership_lost: bool = False
    finalizing: bool = False
    lease_deadline: float | None = None


@dataclass(frozen=True)
class SubmitResult:
    run: dict[str, Any]
    disposition: SubmitDisposition
