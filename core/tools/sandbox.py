"""Встроенные тулы над портом Sandbox: единственный toolset проекта.

Ошибки команд возвращаются моделью-читаемым текстом, а не исключением —
модель сама скорректируется. Вывод усечён для защиты контекста.
"""

from __future__ import annotations

import shlex

from langchain_core.tools import BaseTool, tool

from core.ports import Sandbox, SandboxCommandError

SANDBOX_OUTPUT_MAX_CHARS = 50_000


def _clip(text: str) -> str:
    if len(text) <= SANDBOX_OUTPUT_MAX_CHARS:
        return text
    return text[:SANDBOX_OUTPUT_MAX_CHARS] + "\n... [truncated]"


def build_sandbox_tools(sandbox: Sandbox) -> list[BaseTool]:
    """Тулы, замкнутые на конкретную песочницу (одна на Ран)."""

    @tool
    async def sandbox_run(command: str) -> str:
        """Выполнить shell-команду в изолированной песочнице с клонированным
        репозиторием. Рабочие файлы репозитория лежат в директории репо
        (см. системный промпт). Возвращает stdout; при ненулевом коде выхода —
        текст ошибки с кодом и stderr.

        Args:
            command: shell-команда (git, find, cat, grep и т.п.).
        """
        try:
            return _clip(await sandbox.run(command))
        except SandboxCommandError as exc:
            return _clip(f"exit {exc.exit_code}:\n{exc.stderr}")

    @tool
    async def read_file(path: str) -> str:
        """Прочитать текстовый файл из песочницы по абсолютному пути.

        Args:
            path: абсолютный путь к файлу внутри песочницы.
        """
        try:
            return _clip(await sandbox.run(f"cat -- {shlex.quote(path)}"))
        except SandboxCommandError as exc:
            return _clip(f"exit {exc.exit_code}:\n{exc.stderr}")

    return [sandbox_run, read_file]
