"""Порты (гексагональная архитектура): контракты core к внешнему миру.

Реализации живут в infra/ и передаются в core снаружи (main.py, тесты).
"""

from typing import Protocol


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
