"""Skills — загружаемые пакеты справки по классам уязвимостей и технологиям.

Каждый skill — markdown с YAML-frontmatter (name, description) под
``core/skills/<category>/<name>.md`` (референс strix). Агент подгружает их
инструментом ``load_skill`` как справку в текущий ход — постоянного изменения
промпта нет. Курированный код-релевантный поднабор (статический анализ).
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
MAX_SKILLS_PER_CALL = 5


def _parse_name(text: str, fallback: str) -> tuple[str, str]:
    """(name, description) из frontmatter; имя-файла как fallback."""
    match = _FRONTMATTER.match(text)
    name, description = fallback, ""
    if match:
        for line in match.group(1).splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() == "name":
                name = value.strip() or fallback
            elif sep and key.strip() == "description":
                description = value.strip()
    return name, description


@cache
def _index() -> dict[str, Path]:
    """Имя skill (из frontmatter и из basename) → путь. Оба ключа резолвятся."""
    index: dict[str, Path] = {}
    for path in sorted(_SKILLS_DIR.rglob("*.md")):
        if path.name == "README.md":
            continue
        stem = path.stem
        name, _ = _parse_name(path.read_text(encoding="utf-8"), stem)
        # нормализуем к snake_case: и "sql-injection", и "sql_injection" ведут к файлу
        index[stem] = path
        index[name.replace("-", "_")] = path
    return index


def available_skills() -> list[dict[str, str]]:
    """Каталог: [{name, category, description}] для промпта/UI."""
    out = []
    seen: set[Path] = set()
    for path in sorted(_SKILLS_DIR.rglob("*.md")):
        if path.name == "README.md" or path in seen:
            continue
        seen.add(path)
        name, description = _parse_name(path.read_text(encoding="utf-8"), path.stem)
        out.append(
            {
                "name": name.replace("-", "_"),
                "category": path.parent.name,
                "description": description,
            }
        )
    return out


def validate_requested_skills(names: list[str]) -> str | None:
    """None если ок; иначе текст ошибки с допустимыми именами."""
    if not names:
        return "no skills requested"
    if len(names) > MAX_SKILLS_PER_CALL:
        return f"too many skills ({len(names)} > {MAX_SKILLS_PER_CALL})"
    index = _index()
    unknown = [n for n in names if n.replace("-", "_") not in index]
    if unknown:
        known = ", ".join(sorted({p.stem for p in set(index.values())}))
        return f"unknown skill(s): {', '.join(unknown)}. Known: {known}"
    return None


def load_skills(names: list[str]) -> dict[str, str]:
    """{имя: тело markdown без frontmatter} для запрошенных skills."""
    index = _index()
    out: dict[str, str] = {}
    for name in names:
        path = index.get(name.replace("-", "_"))
        if path is None:
            continue
        text = path.read_text(encoding="utf-8")
        body = _FRONTMATTER.sub("", text, count=1).strip()
        out[path.stem] = body
    return out
