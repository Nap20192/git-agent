"""grep_code: поиск по коду с контекстом — ripgrep, fallback на grep -rn (образ без rg)."""

from __future__ import annotations

import shlex

from langchain_core.tools import BaseTool, tool

from core.ports import Sandbox, SandboxCommandError

MAX_GREP_LINES = 300


def grep_command(
    pattern: str, path: str, *, glob: str = "", context: int = 2, fixed: bool = False
) -> str:
    """Одна shell-команда: rg если есть, иначе grep. Код выхода поисковика сохраняется
    (if без пайпа): 1 — нет совпадений, 2 — ошибка (битый regex и т.п.)."""
    pat, where, ctx = shlex.quote(pattern), shlex.quote(path), max(0, int(context))
    rg = f"rg -n --no-heading --color never -C {ctx}{' -F' if fixed else ''}"
    grep = f"grep -rn -I -C {ctx} {'-F' if fixed else '-E'}"
    if glob:
        rg += f" --glob {shlex.quote(glob)}"
        grep += f" --include={shlex.quote(glob)}"
    return f"if command -v rg >/dev/null 2>&1; then {rg} -e {pat} {where}; else {grep} -e {pat} {where}; fi"


def build_grep_tool(sandbox: Sandbox) -> BaseTool:
    from core.tools.sandbox import _clip

    @tool
    async def grep_code(
        pattern: str, path: str = "", glob: str = "", context: int = 2, fixed: bool = False
    ) -> str:
        """Искать по коду репозитория (ripgrep; regex по умолчанию) с контекстом.

        Формат строк: `файл:номер:текст` (контекст — `файл-номер-текст`).
        Вывод ограничен 300 строками — сужай path/glob или уточняй паттерн.

        Args:
            pattern: regex (rg-синтаксис) или буквальная строка при fixed=true.
            path: абсолютный путь файла/каталога; пусто — корень репозитория.
            glob: фильтр имён файлов, например "*.py" или "**/handlers/*.go".
            context: строк контекста до/после (по умолчанию 2).
            fixed: искать буквально, без regex.
        """
        cmd = grep_command(
            pattern, path or sandbox.repo_dir, glob=glob, context=context, fixed=fixed
        )
        try:
            out = await sandbox.run(cmd)
        except SandboxCommandError as exc:
            if exc.exit_code == 1:
                return f"no matches for {pattern!r}"
            return _clip(f"grep failed (exit {exc.exit_code}):\n{exc.stderr}")
        lines = out.splitlines()
        if len(lines) > MAX_GREP_LINES:
            lines = [
                *lines[:MAX_GREP_LINES],
                f"... [{len(lines) - MAX_GREP_LINES} more lines; narrow path/glob or pattern]",
            ]
        return _clip("\n".join(lines)) if lines else f"no matches for {pattern!r}"

    return grep_code
