"""Общие хелперы eval-харнеса: io / хэши / прайсинг / фолд событий."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# Зеркало core.runtime.schemas / событий (НЕ импортируется — R1; дрифт ловит
# tests/unit/eval/test_signal_mirror.py)
RUN_TERMINAL_STATUSES = ("succeeded", "failed", "interrupted")
USAGE_EVENT_KIND = "usage"
TASK_STARTED_TYPE = "task_started"

# Прайсинг: USD за 1M токенов, снапшотится в манифест каждого прогона.
# ponytail: цены дрейфуют — это калибровочная ручка, правь и ре-снапшоть.
# Сверено с https://api-docs.deepseek.com/quick_start/pricing (2026-09).
PRICING_USD_PER_MILLION: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input_cache_hit": 0.07, "input_cache_miss": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input_cache_hit": 0.14, "input_cache_miss": 0.55, "output": 2.19},
    # неизвестная модель НАМЕРЕННО отсутствует -> price_run вернёт None, не 0
}


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Оборванная жёстким килом последняя строка — скипается с warning:"""
    rows = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"WARN {path}:{lineno}: torn jsonl line skipped", file=sys.stderr)
    return rows


def append_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    path = Path(path)
    needs_newline = False
    if path.exists() and path.stat().st_size > 0:
        with open(path, "rb") as f:
            f.seek(-1, 2)
            needs_newline = f.read(1) != b"\n"
    with open(path, "a", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def canonical_fingerprint(manifest: dict[str, Any]) -> str:
    """Канонический JSON — точный (sort_keys + компактные сепараторы),"""
    return sha256_text(json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str))


def source_tree_sha256(
    root: str | Path, dirs: tuple[str, ...] = ("core", "infra", "pkg", "evals")
) -> str:
    """sha256 всех .py (включая незакоммиченные — ловит то, что git sha не видит)."""
    h = hashlib.sha256()
    root = Path(root)
    for d in dirs:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            h.update(str(p.relative_to(root)).encode())
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def stable_row_id(*parts: str) -> str:
    """Детерминированный id строки: md5, НЕ builtin hash() (PYTHONHASHSEED-соль)."""
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


def price_run(
    usage: dict[str, Any] | None, model: str, pricing: dict[str, dict[str, float]]
) -> float | None:
    """Стоимость рана из снапшота прайсинга; tri-state: None = неизмеримо."""
    p = pricing.get((model or "").strip().lower())
    if usage is None or p is None:
        return None
    try:
        return (
            usage["input_tokens"] * p["input_cache_miss"] + usage["output_tokens"] * p["output"]
        ) / 1e6
    except (KeyError, TypeError):
        return None


def fold_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Свернуть run_events в наблюдаемые сигналы (для бандла и гейта)."""
    usage: dict[str, Any] | None = None
    llm_calls: int | None = None
    usage_events = 0
    served_models: set[str] = set()
    subagent_count = 0
    for event in events:
        payload = event.get("payload") or {}
        if event.get("kind") == USAGE_EVENT_KIND:
            usage_events += 1
            attempt_usage = payload.get("usage")
            if attempt_usage:
                if usage is None:
                    usage = dict(attempt_usage)
                else:
                    for key, value in attempt_usage.items():
                        if isinstance(value, (int, float)):
                            usage[key] = (usage.get(key) or 0) + value
            attempt_calls = payload.get("llm_calls")
            if attempt_calls is not None:
                llm_calls = (llm_calls or 0) + attempt_calls
            for record in payload.get("records") or []:
                name = record.get("model_name")
                if name:
                    served_models.add(str(name))
        data = payload.get("data")
        if isinstance(data, dict) and data.get("type") == TASK_STARTED_TYPE:
            subagent_count += 1
    return {
        "usage": usage,
        "llm_calls": llm_calls,
        "usage_events": usage_events,
        "served_models": sorted(served_models),
        "subagent_count": subagent_count,
    }
