"""Порты (гексагональная архитектура): контракты core к внешнему миру.

Реализации живут в infra/ и передаются в core снаружи (main.py, тесты).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from core.runtime.bridge import StreamItem
    from core.runtime.schemas import LeaseRenewal, StatusFinalization, SubmitDisposition


class SandboxCommandError(RuntimeError):
    def __init__(self, command: str, exit_code: int | None, stderr: str) -> None:
        super().__init__(f"sandbox command failed (exit {exit_code}): {command}\n{stderr}")
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr


class Sandbox(Protocol):
    """Изолированная среда для операций с недоверенным содержимым Репозитория.

    Внутри должны быть доступны git, find, stat, cat (контракт образа/хоста).
    """

    @property
    def repo_dir(self) -> str:
        """Абсолютный путь, куда клонируется Репозиторий внутри песочницы."""
        ...

    async def run(self, command: str, *, timeout_seconds: float | None = None) -> str:
        """Выполняет shell-команду, возвращает stdout.

        Ненулевой код выхода — SandboxCommandError.
        """
        ...

    async def close(self) -> None:
        """Освобождает песочницу; после вызова run недоступен."""
        ...


class RunStore(Protocol):
    """Durable-хранилище Ранов. Каждая мутация — атомарный условный UPDATE (CAS).

    Инварианты: терминальные статусы никогда не перезаписываются; все сравнения
    времени — часами БД; renew_lease с rowcount 0 означает потерю владения.
    """

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
        """Примитив admission. Атомарно: insert / resume / takeover / conflict.

        - строки нет → INSERT pending с owner+lease → (row, created)
        - succeeded → (row, already_succeeded), без мутации
        - failed|interrupted → CAS в pending: новый owner+lease, очистка
          error/stop_reason/cancel_requested_at/report, attempt+1 → (row, resumed)
        - pending|running и lease валиден (>= now - grace) → ConflictError
        - pending|running и lease истёк/NULL → takeover-resume (тот же CAS)
        """
        ...

    async def get(self, run_id: int) -> dict[str, Any] | None: ...

    async def start_run(self, run_id: int, *, owner_worker_id: str) -> bool:
        """CAS pending→running при совпадении владельца (durable-половина барьера)."""
        ...

    async def renew_lease(
        self, run_id: int, *, owner_worker_id: str, lease_seconds: int
    ) -> LeaseRenewal:
        """CAS-продление lease; тем же стейтментом возвращает cancel_requested."""
        ...

    async def request_cancel(self, run_id: int) -> bool:
        """cancel_requested_at = now() для активного рана; first-writer-wins."""
        ...

    async def finalize_if_not_cancelled(
        self, run_id: int, *, owner_worker_id: str, report: dict[str, Any] | None
    ) -> StatusFinalization:
        """CAS running→succeeded, если владелец совпал и cancel не пришёл."""
        ...

    async def finish(
        self,
        run_id: int,
        *,
        owner_worker_id: str,
        status: str,
        error: str | None = None,
        stop_reason: str | None = None,
    ) -> bool:
        """CAS active→failed|interrupted при совпадении владельца."""
        ...

    async def claim_for_takeover(
        self, run_id: int, *, grace_seconds: int, error: str, stop_reason: str
    ) -> bool:
        """CAS active→failed, если lease NULL или истёк (перепроверка при записи)."""
        ...

    async def list_expired(self, *, grace_seconds: int) -> list[dict[str, Any]]:
        """Активные раны с NULL/истёкшим lease (стейл-скан; истина — в CAS takeover)."""
        ...

    async def add_event(self, run_id: int, kind: str, payload: dict[str, Any]) -> None: ...

    async def list_events_after(
        self, run_id: int, after_id: int | None, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Durable-история рана по возрастанию id (id — курсор)."""
        ...


class StreamBridge(Protocol):
    """Мост producer→N consumers c реплеем по курсору и честными пробелами."""

    async def publish(self, run_id: int, event: str, data: Any) -> None: ...

    async def publish_end(self, run_id: int) -> None: ...

    def subscribe(
        self,
        run_id: int,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float | None = None,
    ) -> AsyncIterator[StreamItem]: ...

    async def cleanup(self, run_id: int, *, delay: float = 0) -> None: ...
