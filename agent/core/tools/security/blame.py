"""Blame Находки: кто/когда/каким коммитом внёс уязвимые строки, и входит ли этот
коммит в диапазон изменений текущего События (introducedBy).

Заполняет РАННЕР по данным `git blame --porcelain` в Песочнице — модель blame не
выдумывает; при конфликте прав инструмент. Кэш на ход: (file, start, end) и
ancestry по sha коммита.
"""

from __future__ import annotations

import shlex
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from core.ports import Sandbox, SandboxCommandError
from pkg.logger import get_logger

log = get_logger(__name__)

BLAME_KEYS = (
    "blameAuthor",
    "blameEmail",
    "blameCommit",
    "blameDate",
    "blameCommitMessage",
    "introducedBy",
)
EMPTY_BLAME: dict[str, Any] = dict.fromkeys(BLAME_KEYS)
_UNCOMMITTED = "0" * 40


def _iso(author_time: str, tz: str) -> str | None:
    try:
        sign = -1 if tz.startswith("-") else 1
        hours, minutes = int(tz[1:3]), int(tz[3:5])
        offset = timezone(sign * timedelta(hours=hours, minutes=minutes))
        return datetime.fromtimestamp(int(author_time), tz=offset).isoformat()
    except (ValueError, IndexError):
        try:
            return datetime.fromtimestamp(int(author_time), tz=UTC).isoformat()
        except ValueError:
            return None


def _is_header(line: str) -> bool:
    parts = line.split(" ")
    return (
        len(parts) >= 3
        and len(parts[0]) == 40
        and all(c in "0123456789abcdef" for c in parts[0])
        and parts[1].isdigit()
        and parts[2].isdigit()
    )


def parse_blame_porcelain(text: str) -> dict[str, Any]:
    """Свести `git blame --porcelain` диапазона к ОДНОМУ коммиту: тот, что внёс больше
    строк диапазона (при равенстве — более поздний). Возвращает blame* (без introducedBy).

    Формат: заголовок `<sha> <orig> <final> [<n>]`, далее `author …`, `author-mail <…>`,
    `author-time`, `author-tz`, `summary` (только при первом появлении sha) и строка
    кода с табом. Некоммиченные строки (sha из нулей) не учитываются.
    """
    commits: dict[str, dict[str, Any]] = {}
    lines_by_commit: dict[str, int] = {}
    current: str | None = None
    for raw in text.splitlines():
        if raw.startswith("\t"):
            continue  # сама строка кода
        if _is_header(raw):
            current = raw.split(" ", 1)[0]
            lines_by_commit[current] = lines_by_commit.get(current, 0) + 1
            commits.setdefault(current, {})
            continue
        if current is None:
            continue
        key, _, value = raw.partition(" ")
        if key in ("author", "author-mail", "author-time", "author-tz", "summary"):
            commits[current].setdefault(key, value.strip())
    candidates = [
        (n, int(commits[sha].get("author-time") or 0), sha)
        for sha, n in lines_by_commit.items()
        if sha != _UNCOMMITTED
    ]
    if not candidates:
        return dict(EMPTY_BLAME)
    _, _, sha = max(candidates)
    info = commits[sha]
    return {
        "blameAuthor": info.get("author") or None,
        "blameEmail": (info.get("author-mail") or "").strip("<>") or None,
        "blameCommit": sha,
        "blameDate": _iso(info.get("author-time", ""), info.get("author-tz", "+0000")),
        "blameCommitMessage": info.get("summary") or None,
        "introducedBy": None,
    }


class BlameResolver:
    """Blame + introducedBy над портом Sandbox с кэшем на ход.

    scope_range — (before, after) диапазон изменений События (push: before..after,
    PR: merge-base..head); None — introducedBy не определяется (full_scan, чат).
    """

    def __init__(self, sandbox: Sandbox, scope_range: tuple[str, str] | None = None) -> None:
        self._sandbox = sandbox
        self._range = scope_range
        self._git = f"git -C {shlex.quote(sandbox.repo_dir)}"
        self._blame_cache: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._ancestry_cache: dict[str, str | None] = {}

    async def resolve(self, file: str, start: int, end: int | None = None) -> dict[str, Any]:
        start = max(1, int(start))
        end = max(start, int(end or start))
        key = (file, start, end)
        if key in self._blame_cache:
            return self._blame_cache[key]
        blame = await self._blame(file, start, end)
        if blame.get("blameCommit"):
            blame["introducedBy"] = await self._introduced_by(blame["blameCommit"])
        self._blame_cache[key] = blame
        return blame

    async def _blame(self, file: str, start: int, end: int) -> dict[str, Any]:
        cmd = f"{self._git} blame -L {start},{end} --porcelain -- {shlex.quote(file)}"
        try:
            return parse_blame_porcelain(await self._sandbox.run(cmd))
        except SandboxCommandError as exc:
            log.warning("blame failed", file=file, start=start, stderr=exc.stderr[:200])
            return dict(EMPTY_BLAME)

    async def _introduced_by(self, commit: str) -> str | None:
        """'this_event' если коммит достижим из after, но не из before; иначе 'earlier'."""
        if not self._range:
            return None
        if commit in self._ancestry_cache:
            return self._ancestry_cache[commit]
        before, after = self._range
        result: str | None
        try:
            in_after = await self._is_ancestor(commit, after)
            in_before = await self._is_ancestor(commit, before) if in_after else False
            result = "this_event" if in_after and not in_before else "earlier"
        except SandboxCommandError as exc:  # неизвестный ref диапазона и т.п.
            log.warning("ancestry check failed", commit=commit, stderr=exc.stderr[:200])
            result = None
        self._ancestry_cache[commit] = result
        return result

    async def _is_ancestor(self, commit: str, ref: str) -> bool:
        # exit 0 — предок, 1 — нет, прочее — ошибка (пробрасывается)
        try:
            await self._sandbox.run(
                f"{self._git} merge-base --is-ancestor {shlex.quote(commit)} {shlex.quote(ref)}"
            )
        except SandboxCommandError as exc:
            if exc.exit_code == 1:
                return False
            raise
        return True
