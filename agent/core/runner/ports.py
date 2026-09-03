"""Порты раннера: контракты к hub-БД и backend'у (гексагональная архитектура)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from core.runner.events import Event


class SandboxNotProvisionedError(RuntimeError):
    """У Экземпляра Агента нет живого Экземпляра Сэндбокса — раннер сам НЕ создаёт."""


class InstanceUnavailableError(RuntimeError):
    """Экземпляр нельзя обслужить на этом раннере: держит другой раннер, нет в БД
    или пропал контекст. `outcome` — исход клейма (held_by_other | missing | …)."""

    def __init__(self, instance_id: int, outcome: str) -> None:
        super().__init__(f"instance {instance_id} unavailable: {outcome}")
        self.instance_id = instance_id
        self.outcome = outcome


@dataclass(frozen=True)
class ClaimResult:
    """Итог клейма Экземпляра: claimed | held_by_self | held_by_other | missing."""

    outcome: str
    holder_address: str | None = None


class InstanceStore(Protocol):
    """Операции над hub.* от имени раннера. Мутации статуса — CAS."""

    async def register_runner(self, *, name: str, address: str, slots: int) -> int:
        """Upsert строки hub.runners по имени; возвращает runner_id."""
        ...

    async def heartbeat_runner(self, runner_id: int) -> None: ...

    async def claim_instance(self, instance_id: int, *, runner_id: int) -> ClaimResult:
        """CAS down→running (+runner_id); running у себя — held_by_self."""
        ...

    async def peek_holder(self, instance_id: int, *, runner_id: int) -> ClaimResult:
        """Читающая проверка без клейма: held_by_other (+адрес) | free | held_by_self | missing.

        Для форварда чужих Событий без ожидания слота; гонку с claim решает CAS.
        """
        ...

    async def release_instance(self, instance_id: int, *, runner_id: int) -> bool:
        """CAS running→down только при своём runner_id."""
        ...

    async def begin_event(self, event: Event) -> bool:
        """Журнал дедупа: True — обрабатывать (свежее либо необработанный повтор),
        False — дубль (processed_at уже стоит)."""
        ...

    async def mark_processed(self, instance_id: int, dedup_key: str) -> None: ...

    async def load_context(self, instance_id: int) -> dict[str, Any] | None:
        """Экземпляр + Сборка + connections + Репозиторий одной выборкой."""
        ...

    async def add_report(self, instance_id: int, *, event_id: int | None, summary: str) -> int: ...

    async def add_finding(self, instance_id: int, finding: dict[str, Any]) -> None: ...

    async def add_activity(
        self, instance_id: int, *, event_id: int | None, seq: int, frame: dict[str, Any]
    ) -> None:
        """Кадр activity хода в hub.activity (тикет 012); event_id NULL — чат."""
        ...

    async def list_activity(
        self, instance_id: int, *, event_id: int | None = None, latest: bool = False
    ) -> list[dict[str, Any]]:
        """Реплей кадров хода по seq; latest=True — последний ход Экземпляра."""
        ...


class HubClient(Protocol):
    """HTTP-клиент hub'а (регистрация/heartbeat) и соседних раннеров (форвард).

    hub недоступен ⇒ warn+retry внутри адаптера, не исключение наружу.
    """

    async def register(self, *, name: str, address: str, slots: int) -> None: ...

    async def heartbeat(self, *, runner_id: int) -> None: ...

    async def forward_event(self, address: str, event: Event) -> bool:
        """POST {address}/instances/{id}/events; False при недоступности держателя."""
        ...
