"""Порты (гексагональная архитектура): контракты core к внешнему миру."""

from __future__ import annotations

from typing import Protocol


class SandboxCommandError(RuntimeError):
    def __init__(self, command: str, exit_code: int | None, stderr: str) -> None:
        super().__init__(f"sandbox command failed (exit {exit_code}): {command}\n{stderr}")
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr


class Sandbox(Protocol):
    """Изолированная среда для операций с недоверенным содержимым Репозитория."""

    @property
    def repo_dir(self) -> str:
        """Абсолютный путь, куда клонируется Репозиторий внутри песочницы."""
        ...

    @property
    def id(self) -> str | None:
        """Внешний id Экземпляра (для reconnect/учёта); None для локального."""
        ...

    async def run(self, command: str, *, timeout_seconds: float | None = None) -> str:
        """Выполняет shell-команду, возвращает stdout."""
        ...

    async def close(self) -> None:
        """Отпускает локальные ресурсы (HTTP); НЕ убивает удалённый сэндбокс."""
        ...
