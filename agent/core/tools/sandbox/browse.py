"""browse: открыть веб-страницу и вернуть читаемый текст — для внешних фактов
(документация, advisories, CVE/NVD, README зависимостей), не для чтения репо.

Выполняется В ПЕСОЧНИЦЕ через порт Sandbox: `python3 -c <html_text.py> <url> <bytes>`
(python3 есть в образах strix/latest; нет — честный текст ошибки). Хост только
валидирует схему и усекает вывод.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from urllib.parse import urlsplit

from langchain_core.tools import BaseTool, tool

from core.ports import Sandbox, SandboxCommandError

BROWSE_DEFAULT_MAX_CHARS = 20_000
BROWSE_MAX_CHARS = 50_000
BROWSE_TIMEOUT_SECONDS = 30.0
_FETCH_BYTES_PER_CHAR = 8  # HTML-разметка в разы тяжелее извлечённого текста

_SCRIPT = (Path(__file__).with_name("html_text.py")).read_text(encoding="utf-8")


def browse_command(url: str, max_chars: int) -> str:
    """Shell-команда: python3 обязателен; тело страницы читается не дальше лимита байт."""
    max_bytes = max_chars * _FETCH_BYTES_PER_CHAR
    return (
        "command -v python3 >/dev/null 2>&1 || { echo 'browse: python3 is not installed in the"
        " sandbox image' >&2; exit 3; }; "
        f"python3 -c {shlex.quote(_SCRIPT)} {shlex.quote(url)} {max_bytes}"
    )


def build_browse_tool(sandbox: Sandbox) -> BaseTool:
    @tool
    async def browse(url: str, max_chars: int = BROWSE_DEFAULT_MAX_CHARS) -> str:
        """Открыть веб-страницу (http/https) и вернуть её читаемый текст: заголовок,
        финальный URL после редиректов, текст без скриптов/стилей/навигации с
        сохранением заголовков, списков и блоков кода.

        Для ВНЕШНИХ фактов: документация библиотек, security advisories, страницы
        CVE/NVD/GHSA, README зависимостей. Код репозитория читай read_file/grep_code,
        не через browse.

        Args:
            url: полный http(s)-адрес страницы.
            max_chars: лимит возвращаемого текста (по умолчанию 20000).
        """
        parts = urlsplit(url.strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return f"browse: only http(s) URLs are supported, got {url!r}"
        limit = max(1000, min(int(max_chars), BROWSE_MAX_CHARS))
        try:
            out = await sandbox.run(
                browse_command(url.strip(), limit), timeout_seconds=BROWSE_TIMEOUT_SECONDS
            )
        except SandboxCommandError as exc:
            return f"browse failed (exit {exc.exit_code}):\n{exc.stderr}"[:limit]
        if len(out) > limit:
            out = out[:limit] + f"\n... [truncated at {limit} chars; raise max_chars or narrow]"
        return out

    return browse
