"""Гейт валидности: «ось эксперимента реально применилась?» (офлайн, app-free).

Философия референса: прежде чем верить цифре арма, проверь, что телеметрия
наблюдала то, что конфиг обещал. Ран, проваливший гейт, ИСКЛЮЧАЕТСЯ из
скоринга (помечается gated) — он не считается ни pass, ни fail.

    uv run python evals/validity.py --out evals/runs/smoke1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.common import load_jsonl


def gate_bundle(bundle: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if bundle.get("error") is not None:
        return [f"harness_error: {bundle['error']}"]

    mode = bundle.get("mode")
    served = bundle.get("served_models") or []
    requested = (bundle.get("model") or "").strip().lower()
    if served and any(requested not in s.lower() for s in served):
        problems.append(f"served_model_mismatch: served={served} requested={requested}")

    if (
        mode == "agent"
        and bundle.get("db_status") == "succeeded"
        and not bundle.get("subagent_count")
    ):
        problems.append("agent_axis_not_fired: subagent_count=0 (null experiment)")
    if mode == "pipeline" and bundle.get("subagent_count"):
        problems.append("pipeline_axis_violated: subagent_count>0 (mis-wired profile)")

    memory_config = manifest.get("memory_config") or {}
    if memory_config.get("name") != bundle.get("preset"):
        problems.append(
            f"preset_drift: resolved={memory_config.get('name')} requested={bundle.get('preset')}"
        )

    if memory_config.get("experiment_mode") and bundle.get("usage") is None:
        problems.append("usage_missing: experiment-mode preset without usage telemetry")

    report_commit = bundle.get("report_commit")
    pinned = bundle.get("pinned_commit")
    if report_commit and pinned and report_commit != pinned:
        problems.append(f"commit_drift: analyzed {report_commit[:12]} != pinned {pinned[:12]}")
    return problems


def gate(out: Path) -> dict[str, list[str]]:
    config = json.loads((out / "run_config.json").read_text())
    manifest = config["_manifest"]
    result: dict[str, list[str]] = {}
    for bundle in load_jsonl(out / "bundles.jsonl"):
        problems = gate_bundle(bundle, manifest)
        if problems:
            result[bundle["unit_key"]] = problems
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    problems = gate(Path(args.out))
    if not problems:
        print("GATE CLEAN: все бандлы валидны")
        return
    for key, issues in problems.items():
        for issue in issues:
            print(f"GATED {key}: {issue}")
    print(f"\n{len(problems)} бандл(ов) исключено из скоринга")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
