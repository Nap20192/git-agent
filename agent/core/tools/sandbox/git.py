"""git_diff / git_blame над клоном в песочнице.

Клон — shallow: коммит События фетчится с --depth 2 (core/repo.py), поэтому дифф
`ref^..ref` доступен; более глубокая история — `git fetch --deepen=N` через sandbox_run.
"""

from __future__ import annotations

import shlex

from langchain_core.tools import BaseTool, tool

from core.ports import Sandbox, SandboxCommandError

SHALLOW_HINT = (
    "\n(hint: the clone is shallow; run `git fetch --deepen=20 origin` via sandbox_run and retry)"
)


def build_git_tools(sandbox: Sandbox) -> list[BaseTool]:
    from core.tools.sandbox import _clip

    git = f"git -C {shlex.quote(sandbox.repo_dir)}"

    def _failed(what: str, exc: SandboxCommandError) -> str:
        text = f"{what} failed (exit {exc.exit_code}):\n{exc.stderr}"
        if "unknown revision" in exc.stderr or "bad revision" in exc.stderr:
            text += SHALLOW_HINT
        return _clip(text)

    @tool
    async def git_diff(
        ref: str = "HEAD", base: str = "", path: str = "", stat: bool = False
    ) -> str:
        """Изменения коммита или диапазона: что именно внёс коммит События.

        Без base — изменения самого коммита ref (git show; корневой и merge-коммиты
        тоже). Начни со stat=true (список файлов), затем дифф по конкретному path.

        Args:
            ref: коммит/ref (по умолчанию HEAD — коммит События).
            base: начальный коммит диапазона base..ref; пусто — родитель ref.
            path: ограничить путём (относительно корня репозитория).
            stat: только сводка по файлам (--stat).
        """
        opts = " --stat" if stat else ""
        tail = f" -- {shlex.quote(path)}" if path else ""
        cmd = (
            f"{git} diff --no-color{opts} {shlex.quote(base)} {shlex.quote(ref)}{tail}"
            if base
            else f"{git} show --no-color --format={opts} {shlex.quote(ref)}{tail}"
        )
        try:
            out = await sandbox.run(cmd)
        except SandboxCommandError as exc:
            return _failed("git diff", exc)
        return _clip(out) if out.strip() else "(empty diff)"

    @tool
    async def git_blame(path: str, start_line: int = 1, end_line: int = 0) -> str:
        """Кто и в каком коммите внёс строки файла (blame диапазона).

        В shallow-клоне граничные коммиты помечены `^` — это край истории, не автор.

        Args:
            path: путь файла относительно корня репозитория.
            start_line: первая строка диапазона (с 1).
            end_line: последняя строка; 0 — start_line+50.
        """
        start = max(1, int(start_line))
        end = int(end_line) or start + 50
        try:
            out = await sandbox.run(
                f"{git} blame --date=short -L {start},{max(start, end)} -- {shlex.quote(path)}"
            )
        except SandboxCommandError as exc:
            return _failed("git blame", exc)
        return _clip(out)

    return [git_diff, git_blame]
