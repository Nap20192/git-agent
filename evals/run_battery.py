"""Онлайн-раннер батареи: единственный модуль харнеса, трогающий приложение.

Тратит реальные API-деньги (DeepSeek) и требует Postgres + OpenSandbox.
Пишет вечные артефакты: runs/<name>/{run_config.json, bundles.jsonl} — один
бандл на (unit, mode, preset, trial). Грейдинг потом офлайн и бесплатно.

Детерминизм: трейсинг выключается ДО первого импорта core.* (load_dotenv и
core.tracing читают env при импорте) — все app-импорты функционально-локальны.

Запуск:
    uv run python evals/run_battery.py --battery evals/data/repos.v1.jsonl \
        --out evals/runs/smoke1 --mode pipeline --preset prod --limit 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# R2: до любого импорта core.*/infra.*
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGFUSE_TRACING"] = "false"

from evals.battery import load_battery  # noqa: E402
from evals.common import (  # noqa: E402
    PRICING_USD_PER_MILLION,
    SCHEMA_VERSION,
    append_jsonl,
    canonical_fingerprint,
    fold_events,
    load_jsonl,
    price_run,
    sha256_file,
    source_tree_sha256,
)

UNIT_TIMEOUT_SECONDS = float(os.environ.get("EVAL_UNIT_TIMEOUT", "900"))

# Аргументы, НЕ входящие в fingerprint: «куда писать/сколько», не «что меряем»
_NON_SCIENTIFIC_ARGS = {"out", "limit", "ids", "allow_deprecated"}


def _git(cmd: list[str]) -> str:
    try:
        return subprocess.run(
            ["git", *cmd], cwd=_ROOT, capture_output=True, text=True, timeout=15
        ).stdout.strip()
    except Exception:
        return "unavailable"


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    from dataclasses import asdict

    from core.memory import resolve_memory_preset  # функционально-локально (R2)

    memory_config = asdict(resolve_memory_preset(args.preset, model_name=args.model))
    return {
        "schema_version": SCHEMA_VERSION,
        "git_sha": _git(["rev-parse", "HEAD"]),
        "git_status": _git(["status", "--short"]),
        "source_tree_sha256": source_tree_sha256(_ROOT),
        "uv_lock_sha256": sha256_file(_ROOT / "uv.lock"),
        "battery_path": str(Path(args.battery).resolve()),
        "battery_sha256": sha256_file(args.battery),
        "mode": args.mode,
        "preset": args.preset,
        "model": args.model,
        "sandbox": args.sandbox,
        "trials": args.trials,
        "memory_config": memory_config,
        "pricing_snapshot_usd_per_million": PRICING_USD_PER_MILLION,
        "runner_args": {k: v for k, v in vars(args).items() if k not in _NON_SCIENTIFIC_ARGS},
    }


def write_or_validate_run_config(
    out: Path, args: argparse.Namespace, manifest: dict[str, Any], fp: str
) -> None:
    config_path = out / "run_config.json"
    bundles_path = out / "bundles.jsonl"
    if config_path.exists() and bundles_path.exists() and bundles_path.stat().st_size > 0:
        stored = json.loads(config_path.read_text())
        if stored.get("_fingerprint") != fp:
            raise SystemExit(
                f"REFUSED: out dir {out} holds bundles for fingerprint"
                f" {stored.get('_fingerprint', '?')[:12]}…, current config gives {fp[:12]}…."
                " Use a fresh --out (научная конфигурация изменилась)."
            )
        return
    out.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {**vars(args), "_fingerprint": fp, "_manifest": manifest},
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


def completed_unit_keys(bundles_path: Path) -> set[str]:
    """Ключи юнитов с чистым (error is None) бандлом — скипаются при resume."""
    if not bundles_path.exists():
        return set()
    return {
        row["unit_key"]
        for row in load_jsonl(bundles_path)
        if row.get("error") is None and row.get("unit_key")
    }


async def run_unit(
    runtime: Any,
    store: Any,
    unit: dict[str, Any],
    *,
    args: argparse.Namespace,
    fp: str,
    trial: int,
) -> dict[str, Any]:
    from core.config import settings  # функционально-локально

    unit_key = f"{unit['unit_id']}~{args.mode}~{args.preset}~t{trial}"
    # ponytail: commit_sha в runs — durable-МЕТКА, не checkout-реф (пин едет
    # отдельным checkout_ref), поэтому неймспейсинг даёт каждому арму свою
    # строку runs, не меняя поведение агента. Апгрейд: отдельная identity-колонка.
    identity_sha = f"{unit['commit_sha'][:12]}~{fp[:12]}~{args.mode}~{args.preset}~t{trial}"
    started = time.time()
    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": fp,
        "unit_key": unit_key,
        "unit_id": unit["unit_id"],
        "repo_url": unit["repo_url"],
        "pinned_commit": unit["commit_sha"],
        "mode": args.mode,
        "preset": args.preset,
        "model": args.model,
        "sandbox": args.sandbox,
        "trial": trial,
        "error": None,
    }
    try:
        async with asyncio.timeout(UNIT_TIMEOUT_SECONDS):
            result = await runtime.submit(
                repo_url=unit["repo_url"],
                commit_sha=identity_sha,
                llm_api_base=settings.llm_api_base,
                llm_api_key=settings.llm_api_key,
                llm_model=args.model,
                sandbox_name=args.sandbox,
                checkout_ref=unit["commit_sha"],
            )
            run_id = result.run["id"]
            row = await runtime.wait(run_id)
            events = await store.list_events_after(run_id, None, limit=10_000)
    except TimeoutError:
        bundle["error"] = f"TimeoutError: unit exceeded {UNIT_TIMEOUT_SECONDS}s"
        return bundle
    except Exception as exc:
        bundle["error"] = f"{type(exc).__name__}: {exc}"
        return bundle

    folded = fold_events(events)
    report = row.get("report")
    bundle.update(
        run_id=run_id,
        db_status=str(row.get("status")),
        db_attempt=row.get("attempt"),
        db_error=row.get("error"),
        stop_reason=row.get("stop_reason"),
        report=report,
        report_commit=(report or {}).get("commit"),
        wall_time_s=round(time.time() - started, 2),
        **folded,
        cost_usd=price_run(folded["usage"], args.model, PRICING_USD_PER_MILLION),
    )
    return bundle


async def run_all(args: argparse.Namespace) -> None:
    from core.agents.llm import make_model
    from core.lead import build_lead_profile
    from core.runtime import MemoryStreamBridge, Runtime
    from core.runtime.profile import PIPELINE_PROFILE
    from infra.postgres import get_or_create_repository
    from infra.run_store import PostgresRunStore
    from infra.sandboxes import create_sandbox_by_name

    manifest = build_manifest(args)
    fp = canonical_fingerprint(manifest)
    out = Path(args.out)
    write_or_validate_run_config(out, args, manifest, fp)
    bundles_path = out / "bundles.jsonl"
    done = completed_unit_keys(bundles_path)

    units = load_battery(args.battery, allow_deprecated=args.allow_deprecated)
    if args.ids:
        wanted = set(args.ids.split(","))
        units = [u for u in units if u["unit_id"] in wanted]
    if args.limit:
        units = units[: args.limit]

    # Пресет применяется штатным каналом выбора приложения (env)
    os.environ["GIT_AGENT_MEMORY_PRESET"] = args.preset

    async def repository(url: str) -> dict[str, Any]:
        return await asyncio.to_thread(get_or_create_repository, url)

    store = PostgresRunStore()
    profile = build_lead_profile() if args.mode == "agent" else PIPELINE_PROFILE
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from core.config import settings

    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        runtime = Runtime(
            store=store,
            bridge=MemoryStreamBridge(),
            make_model=make_model,
            create_sandbox=create_sandbox_by_name,
            get_or_create_repository=repository,
            profile=profile,
            checkpointer=checkpointer,
        )
        await runtime.start()
        try:
            total = len(units) * args.trials
            n = 0
            for trial in range(1, args.trials + 1):
                for unit in units:
                    n += 1
                    unit_key = f"{unit['unit_id']}~{args.mode}~{args.preset}~t{trial}"
                    if unit_key in done:
                        print(f"[{n}/{total}] skip (done): {unit_key}")
                        continue
                    print(f"[{n}/{total}] run: {unit_key}", flush=True)
                    bundle = await run_unit(runtime, store, unit, args=args, fp=fp, trial=trial)
                    append_jsonl(bundles_path, [bundle])
                    status = bundle.get("db_status") or f"ERROR: {bundle['error']}"
                    print(f"    -> {status}  cost={bundle.get('cost_usd')}", flush=True)
        finally:
            await runtime.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Прогон eval-батареи (платно!)")
    parser.add_argument("--battery", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=["pipeline", "agent"], default="pipeline")
    parser.add_argument("--preset", default="prod")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--sandbox", default="git")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", default="", help="comma-separated unit_id filter")
    parser.add_argument("--allow-deprecated", action="store_true")
    args = parser.parse_args()
    asyncio.run(run_all(args))


if __name__ == "__main__":
    main()
