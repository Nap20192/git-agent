"""Офлайн код-грейд: покрытие фактов по бандлам. Бесплатно, повторяемо вечно.

Никогда не импортирует core.*/infra.* (R1). Tri-state на каждый факт:
True/False/None, где None = «неизмеримо в этом режиме» и НИКОГДА не fail.

Tool-fair: у каждого факта две оценки — structured (точная, по полям
pipeline-отчёта) и prose (по текстовому представлению; работает в обоих
режимах). Кросс-режимный хедлайн — prose.

    uv run python evals/grade.py --out evals/runs/smoke1 --battery evals/data/repos.v1.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.battery import check_fact_prose, check_fact_structured, load_battery
from evals.common import SCHEMA_VERSION, load_jsonl, stable_row_id, write_jsonl


def proseview(report: dict[str, Any] | None) -> str | None:
    """Текстовое представление отчёта: проза + весь JSON (substring-поиск)."""
    if report is None:
        return None
    parts = []
    for key in ("answer", "description"):
        value = report.get(key)
        if isinstance(value, str):
            parts.append(value)
    parts.append(json.dumps(report, ensure_ascii=False))
    return "\n".join(parts)


def grade_bundle(
    bundle: dict[str, Any],
    unit: dict[str, Any],
    manifest: dict[str, Any],
    *,
    expected_fingerprint: str | None = None,
) -> dict[str, Any]:
    gate_problems = gate_bundle_cached(bundle, manifest)
    if (
        expected_fingerprint
        and bundle.get("fingerprint")
        and bundle["fingerprint"] != expected_fingerprint
    ):
        # бандл из чужого прогона подложен в этот out-дир — не грейдим
        gate_problems = [
            f"fingerprint_mismatch: bundle {bundle['fingerprint'][:12]}"
            f" != config {expected_fingerprint[:12]}",
            *gate_problems,
        ]
    gated = bool(gate_problems)

    row: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "row_id": stable_row_id(str(bundle.get("run_id", "")), bundle["unit_key"]),
        "unit_key": bundle["unit_key"],
        "unit_id": bundle["unit_id"],
        "run_id": bundle.get("run_id"),
        "mode": bundle.get("mode"),
        "preset": bundle.get("preset"),
        "model": bundle.get("model"),
        "trial": bundle.get("trial"),
        "db_status": bundle.get("db_status"),
        "error": bundle.get("error"),
        "gated": gated,
        "gate_problems": gate_problems,
        "usage": bundle.get("usage"),
        "cost_usd": bundle.get("cost_usd"),
        "grade_source": "auto",
    }

    expected_status = unit.get("expected_status", "succeeded")
    if expected_status == "failed":
        # error-кейс: pass = ран управляемо зафейлился (не крах харнеса)
        passed = bundle.get("db_status") == "failed" and bundle.get("error") is None
        row.update(
            behavior_pass=None if gated else passed,
            facts_total=0,
            facts_measured_prose=0,
            facts_pass_prose=0,
            facts_measured_struct=0,
            facts_pass_struct=0,
            fact_detail=[],
        )
        return row

    # expected succeeded: behavior = ран реально дошёл до succeeded. Иначе
    # app-failed ран невидим (все факты None -> он просто исчезает из покрытия).
    behavior = None if gated else bundle.get("db_status") == "succeeded"

    report = bundle.get("report") if not gated else None
    prose = proseview(report)
    detail = []
    measured_p = pass_p = measured_s = pass_s = 0
    for fact in unit["facts"]:
        structured = check_fact_structured(fact, report) if not gated else None
        prose_result = check_fact_prose(fact, prose) if not gated else None
        if structured is not None:
            measured_s += 1
            pass_s += int(structured)
        if prose_result is not None:
            measured_p += 1
            pass_p += int(prose_result)
        detail.append(
            {
                "fact_id": fact["fact_id"],
                "structured_pass": structured,
                "prose_pass": prose_result,
            }
        )
    row.update(
        behavior_pass=behavior,
        facts_total=len(unit["facts"]),
        facts_measured_prose=measured_p,
        facts_pass_prose=pass_p,
        facts_measured_struct=measured_s,
        facts_pass_struct=pass_s,
        fact_detail=detail,
    )
    return row


# gate_bundle из validity — переиспользуем без повторного чтения манифеста
def gate_bundle_cached(bundle: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    from evals.validity import gate_bundle as _gate

    return _gate(bundle, manifest)


def grade_run(out: Path, battery_path: Path, *, allow_deprecated: bool = False) -> Path:
    config = json.loads((out / "run_config.json").read_text())
    manifest = config["_manifest"]
    expected_fp = config.get("_fingerprint")
    units = {u["unit_id"]: u for u in load_battery(battery_path, allow_deprecated=allow_deprecated)}
    rows = []
    for bundle in load_jsonl(out / "bundles.jsonl"):
        unit = units.get(bundle["unit_id"])
        if unit is None:
            continue  # юнит вне этой батареи (например, отфильтрован в v2)
        rows.append(grade_bundle(bundle, unit, manifest, expected_fingerprint=expected_fp))
    rows.sort(key=lambda r: r["row_id"])  # детерминированный порядок
    grades_path = out / "grades.jsonl"
    write_jsonl(grades_path, rows)
    return grades_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--battery", required=True)
    parser.add_argument("--allow-deprecated", action="store_true")
    args = parser.parse_args()
    path = grade_run(Path(args.out), Path(args.battery), allow_deprecated=args.allow_deprecated)
    rows = load_jsonl(path)
    gated = sum(1 for r in rows if r["gated"])
    print(f"graded {len(rows)} bundles -> {path} (gated: {gated})")


if __name__ == "__main__":
    main()
