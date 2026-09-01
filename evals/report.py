"""Отчёт: сравнение армов (mode/preset/model). Офлайн, app-free, read-only.

Честность отчёта (R9/R10): хедлайн — работа/стоимость (покрытие фактов,
токены И доллары вместе — кэш/префикс-эффекты разводят их); n= в каждой
ячейке; gated/errors на виду; $ — верхняя граница (input по cache-miss,
помечено); латентности в хедлайне нет (single-shot, конфаунд).

    uv run python evals/report.py --out evals/runs/smoke1 [--out evals/runs/smoke2 ...]
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.common import load_jsonl


def _arm(row: dict[str, Any]) -> tuple[str, str, str]:
    return (row.get("mode") or "?", row.get("preset") or "?", row.get("model") or "?")


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_arm: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        by_arm[_arm(row)].append(row)

    out = []
    for arm, arm_rows in sorted(by_arm.items()):
        clean = [r for r in arm_rows if not r["gated"] and r["error"] is None]
        gated = sum(1 for r in arm_rows if r["gated"])
        errors = sum(1 for r in arm_rows if r["error"] is not None)
        mp = sum(r["facts_measured_prose"] for r in clean)
        pp = sum(r["facts_pass_prose"] for r in clean)
        ms = sum(r["facts_measured_struct"] for r in clean)
        ps = sum(r["facts_pass_struct"] for r in clean)
        behavior = [r["behavior_pass"] for r in clean if r["behavior_pass"] is not None]
        usages = [r["usage"] for r in clean if r["usage"]]
        costs = [r["cost_usd"] for r in clean if r["cost_usd"] is not None]
        out.append(
            {
                "mode": arm[0],
                "preset": arm[1],
                "model": arm[2],
                "n": len(clean),
                "fact_cov_prose": f"{pp}/{mp}" if mp else "—",
                "fact_cov_prose_pct": round(100 * pp / mp, 1) if mp else None,
                "fact_cov_struct": f"{ps}/{ms}" if ms else "—",
                "behavior_pass": f"{sum(behavior)}/{len(behavior)}" if behavior else "—",
                "input_tokens": sum(u["input_tokens"] for u in usages) if usages else None,
                "output_tokens": sum(u["output_tokens"] for u in usages) if usages else None,
                "cost_usd_upper": round(sum(costs), 4) if costs else None,
                "usage_n": len(usages),
                "gated": gated,
                "errors": errors,
            }
        )
    return out


def report(outs: list[Path]) -> None:
    rows: list[dict[str, Any]] = []
    for out in outs:
        rows.extend(load_jsonl(out / "grades.jsonl"))
    if not rows:
        print("нет grades.jsonl — сначала evals/grade.py")
        return
    arms = aggregate(rows)

    header = (
        f"{'arm':44} {'n':>3} {'facts(prose)':>13} {'facts(struct)':>14}"
        f" {'behavior':>9} {'in_tok':>10} {'out_tok':>9} {'$upper':>8} {'gated':>6} {'err':>4}"
    )
    print(header)
    print("-" * len(header))
    for a in arms:
        arm_name = f"{a['mode']}/{a['preset']}/{a['model']}"
        pct = f" ({a['fact_cov_prose_pct']}%)" if a["fact_cov_prose_pct"] is not None else ""
        print(
            f"{arm_name:44} {a['n']:>3} {a['fact_cov_prose'] + pct:>13} {a['fact_cov_struct']:>14}"
            f" {a['behavior_pass']:>9} {a['input_tokens'] if a['input_tokens'] is not None else '—':>10}"
            f" {a['output_tokens'] if a['output_tokens'] is not None else '—':>9}"
            f" {a['cost_usd_upper'] if a['cost_usd_upper'] is not None else '—':>8}"
            f" {a['gated']:>6} {a['errors']:>4}"
        )
    print(
        "\nПримечания: все грейды — (auto only, binary rules). $ — ВЕРХНЯЯ граница"
        " (input по cache-miss тарифу; точнее — при появлении cache-телеметрии)."
        " Латентность не показывается (конфаунд последовательных прогонов)."
        " gated-раны исключены из покрытия. Токены смотреть ВМЕСТЕ с $."
    )

    csv_path = outs[0] / "report_by_arm.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(arms[0].keys()))
        writer.writeheader()
        writer.writerows(arms)
    print(f"\ncsv: {csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", action="append", required=True, dest="outs")
    args = parser.parse_args()
    report([Path(o) for o in args.outs])


if __name__ == "__main__":
    main()
