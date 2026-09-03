"""Встроенные тулы над портом Sandbox: единственный toolset проекта (Лид и Сабагенты).

Образ Песочницы (deploy/sandbox/Dockerfile, `task sandbox:image`):
- `git-agent/sandbox:strix` — рабочий сейчас (офлайн поверх strix-sandbox): git, rg,
  semgrep, bandit, node, go, nuclei, nmap; gosec и osv-scanner НЕТ;
- `git-agent/sandbox:latest` — полный (плюс jq, curl, python3.12, npm, gosec,
  osv-scanner), пока не собирается (Docker Hub недоступен).
Анализаторы тулы не устанавливают и на конкретный набор не полагаются: перед запуском
анализатора через sandbox_run проверяй `command -v <bin>`. На минимальном alpine/git
работает всё, кроме rg (grep_code падает на grep -rn) и browse (нужен python3).

Ошибки команд возвращаются моделью-читаемым текстом, а не исключением —
модель сама скорректируется. Вывод усечён для защиты контекста.
"""

from __future__ import annotations

import shlex

from langchain_core.tools import BaseTool, tool

from core.ports import Sandbox, SandboxCommandError

SANDBOX_OUTPUT_MAX_CHARS = 50_000
READ_DEFAULT_LIMIT = 400  # строк за один read_file
LIST_MAX_ENTRIES = 500


def _clip(text: str) -> str:
    if len(text) <= SANDBOX_OUTPUT_MAX_CHARS:
        return text
    return text[:SANDBOX_OUTPUT_MAX_CHARS] + "\n... [truncated]"


def _error(exc: SandboxCommandError) -> str:
    return _clip(f"exit {exc.exit_code}:\n{exc.stderr}")


def build_sandbox_tools(sandbox: Sandbox) -> list[BaseTool]:
    """Тулы, замкнутые на конкретную песочницу (одна на Ран)."""
    from core.tools.sandbox.browse import build_browse_tool
    from core.tools.sandbox.git import build_git_tools
    from core.tools.sandbox.search import build_grep_tool

    @tool
    async def sandbox_run(command: str) -> str:
        """Выполнить shell-команду в изолированной песочнице с клонированным
        репозиторием. В образе есть git, rg, semgrep, bandit, node, go (состав
        зависит от тега образа — перед запуском анализатора проверь `command -v`).
        Рабочие файлы репозитория лежат в директории репо (см. системный промпт).
        Возвращает stdout; при ненулевом коде выхода — текст ошибки с кодом и stderr.
        Для чтения/поиска/истории предпочитай read_file, list_dir, grep_code,
        git_diff, git_blame.

        Args:
            command: shell-команда (semgrep, bandit, find, wc и т.п.).
        """
        try:
            return _clip(await sandbox.run(command))
        except SandboxCommandError as exc:
            return _error(exc)

    @tool
    async def read_file(path: str, offset: int = 1, limit: int = READ_DEFAULT_LIMIT) -> str:
        """Прочитать текстовый файл из песочницы постранично, с номерами строк.

        Возвращает строки [offset, offset+limit) в формате `N\\tтекст` и футер
        `(lines a-b of N)` — по нему видно, сколько осталось; для продолжения
        зови с offset=b+1.

        Args:
            path: абсолютный путь к файлу внутри песочницы.
            offset: номер первой строки (с 1).
            limit: сколько строк вернуть (по умолчанию 400).
        """
        start = max(1, int(offset))
        end = start + max(1, int(limit)) - 1
        script = (
            f'NR>={start} && NR<={end} {{printf "%d\\t%s\\n", NR, $0}}'
            f' END {{if (NR<{start}) printf "(file has %d lines; offset {start} is beyond end)\\n", NR;'
            f' else printf "(lines {start}-%d of %d)\\n", (NR<{end}?NR:{end}), NR}}'
        )
        try:
            return _clip(await sandbox.run(f"awk {shlex.quote(script)} {shlex.quote(path)}"))
        except SandboxCommandError as exc:
            return _error(exc)

    @tool
    async def list_dir(path: str = "", depth: int = 2) -> str:
        """Показать дерево файлов и каталогов (без .git) до заданной глубины.

        Args:
            path: абсолютный путь каталога; пусто — корень репозитория.
            depth: глубина обхода (по умолчанию 2).
        """
        root = shlex.quote(path or sandbox.repo_dir)
        cmd = (
            f"find {root} -maxdepth {max(1, int(depth))} -name .git -prune -o -print"
            f" | sort | head -n {LIST_MAX_ENTRIES + 1}"
        )
        try:
            out = await sandbox.run(cmd)
        except SandboxCommandError as exc:
            return _error(exc)
        lines = out.splitlines()
        if len(lines) > LIST_MAX_ENTRIES:
            lines = [
                *lines[:LIST_MAX_ENTRIES],
                f"... [more than {LIST_MAX_ENTRIES} entries; narrow path or depth]",
            ]
        return _clip("\n".join(lines))

    return [
        sandbox_run,
        read_file,
        list_dir,
        build_grep_tool(sandbox),
        *build_git_tools(sandbox),
        build_browse_tool(sandbox),
    ]
