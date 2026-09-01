"""Батареи: загрузка, линт, и запиненный набор правил проверки фактов.

Батарея — замороженный JSONL: одна запись на repo-unit, запиненный
(repo_url, commit_sha) + руками написанные атомарные бинарно-проверяемые
факты. Ground truth НИКОГДА не генерируется LLM. Исправление батареи =
новый файл repos.v2.jsonl; старый — в DEPRECATED_BATTERIES (запуск блокируется,
репродукция — за явным --allow-deprecated).

Правила — закрытый enum: неизвестное правило — жёсткая ошибка линта, не skip.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FACT_RULES = (
    "structured_eq",
    "structured_contains",
    "structured_set_superset",
    "prose_substring",
    "prose_regex",
    "absent",
)

DEPRECATED_BATTERIES: dict[str, str] = {
    # "repos.v1.jsonl": "причина депрекации",
}


class BatteryError(ValueError):
    pass


def load_battery(path: str | Path, *, allow_deprecated: bool = False) -> list[dict[str, Any]]:
    path = Path(path)
    if path.name in DEPRECATED_BATTERIES and not allow_deprecated:
        raise BatteryError(
            f"battery {path.name} is DEPRECATED: {DEPRECATED_BATTERIES[path.name]}."
            " Use the successor; --allow-deprecated only for reproduction."
        )
    units = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                units.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise BatteryError(f"{path.name}:{lineno}: invalid JSON: {exc}") from exc
    lint_battery(units, name=path.name)
    return units


def lint_battery(units: list[dict[str, Any]], *, name: str = "<battery>") -> None:
    seen_ids: set[str] = set()
    for unit in units:
        uid = unit.get("unit_id")
        if not uid or not isinstance(uid, str):
            raise BatteryError(f"{name}: unit without unit_id: {unit}")
        if uid in seen_ids:
            raise BatteryError(f"{name}: duplicate unit_id {uid!r}")
        seen_ids.add(uid)
        for key in ("repo_url", "commit_sha"):
            if not unit.get(key):
                raise BatteryError(f"{name}:{uid}: missing {key!r}")
        expected_status = unit.get("expected_status", "succeeded")
        if expected_status not in ("succeeded", "failed"):
            raise BatteryError(f"{name}:{uid}: bad expected_status {expected_status!r}")
        if not unit.get("facts") and expected_status != "failed":
            raise BatteryError(
                f"{name}:{uid}: missing 'facts' (allowed only for expected_status=failed)"
            )
        unit.setdefault("facts", [])
        fact_ids: set[str] = set()
        for fact in unit["facts"]:
            fid = fact.get("fact_id")
            if not fid or fid in fact_ids:
                raise BatteryError(f"{name}:{uid}: missing/duplicate fact_id in {fact}")
            fact_ids.add(fid)
            rule = fact.get("rule")
            if rule not in FACT_RULES:
                raise BatteryError(
                    f"{name}:{uid}:{fid}: unknown rule {rule!r}; allowed: {FACT_RULES}"
                )
            if rule.startswith("structured") and not fact.get("path"):
                raise BatteryError(f"{name}:{uid}:{fid}: structured rule needs 'path'")
            if rule in ("prose_substring", "prose_regex") and not fact.get("prose"):
                raise BatteryError(f"{name}:{uid}:{fid}: prose rule needs 'prose'")
            if rule == "absent" and not (fact.get("prose") or fact.get("path")):
                raise BatteryError(f"{name}:{uid}:{fid}: absent rule needs 'prose' or 'path'")
            if rule == "prose_regex" or (rule == "absent" and fact.get("prose")):
                try:
                    re.compile(fact["prose"])
                except re.error as exc:
                    raise BatteryError(f"{name}:{uid}:{fid}: bad regex: {exc}") from exc


def _resolve_path(report: dict[str, Any], dotted: str) -> Any:
    node: Any = report
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


_MISSING = object()


def check_fact_structured(fact: dict[str, Any], report: dict[str, Any] | None) -> bool | None:
    """Структурная проверка; None = неизмеримо (нет path в отчёте)."""
    if report is None or not fact.get("path"):
        return None
    resolved = _resolve_path(report, fact["path"])
    if resolved is _MISSING:
        return None if fact["rule"] != "absent" else True
    rule = fact["rule"]
    if rule == "structured_eq":
        return str(resolved) == str(fact.get("value"))
    if rule == "structured_contains":
        value = str(fact.get("value", ""))
        if isinstance(resolved, str):
            return value.lower() in resolved.lower()
        if isinstance(resolved, list):
            return any(value.lower() in str(x).lower() for x in resolved)
        if isinstance(resolved, dict):
            return any(value.lower() in str(k).lower() for k in resolved)
        return False
    if rule == "structured_set_superset":
        if not isinstance(resolved, list):
            return False
        haystack = " | ".join(str(x).lower() for x in resolved)
        return all(str(v).lower() in haystack for v in fact.get("values", []))
    if rule == "absent":
        value = str(fact.get("value", "")).lower()
        blob = json.dumps(resolved, ensure_ascii=False).lower()
        return value not in blob
    return None  # prose-правила не измеряются структурно


def check_fact_prose(fact: dict[str, Any], proseview: str | None) -> bool | None:
    """Прозовая проверка; None = неизмеримо (нет prose-цели или текста)."""
    prose = fact.get("prose")
    if proseview is None or not prose:
        return None
    rule = fact["rule"]
    if rule == "prose_substring":
        return prose.lower() in proseview.lower()
    if rule in (
        "prose_regex",
        "absent",
        "structured_eq",
        "structured_contains",
        "structured_set_superset",
    ):
        found = re.search(prose, proseview, re.IGNORECASE) is not None
        return (not found) if rule == "absent" else found
    return None
