"""CLI: uv run main.py <repo-url> [--mode pipeline|agent] [--model … --sandbox …]

Ран исполняется через durable-рантайм: пишется в БД, ведёт историю в run_events,
переживает падение (resubmit возобновляет с чекпоинта под тем же id).
"""

import argparse
import asyncio
import json
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.agents.llm import make_model
from core.config import settings
from core.lead import build_lead_profile
from core.runtime import MemoryStreamBridge, Runtime
from core.runtime.bridge import END_SENTINEL, StreamGap
from core.runtime.profile import PIPELINE_PROFILE
from infra.postgres import get_or_create_repository
from infra.run_store import PostgresRunStore
from infra.sandboxes import DEFAULT_SANDBOX, create_sandbox_by_name
from pkg.logger import get_logger

log = get_logger("main")


async def _resolve_commit_sha(repo_url: str) -> str:
    """HEAD-коммит без clone: ls-remote для URL, rev-parse для локального пути."""
    import os

    args = (
        ["git", "-C", repo_url, "rev-parse", "HEAD"]
        if os.path.isdir(repo_url)
        else ["git", "ls-remote", repo_url, "HEAD"]
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        token = out.decode().split()[0] if out.split() else ""
        return token or "unknown"
    except Exception:
        log.warning("commit sha resolution failed; using 'unknown'", repo_url=repo_url)
        return "unknown"


def _fmt_step(data: dict) -> str:
    """Одна строка про шаг сабагента (ход модели или результат тула)."""
    if data.get("kind") == "ai" and data.get("tool_calls"):
        calls = ", ".join(
            f"{c.get('name')}({str(c.get('args', ''))[:60]})" for c in data["tool_calls"]
        )
        return f"      → {calls}"
    if data.get("kind") == "tool":
        return f"      ⤷ {data.get('tool_name', 'tool')}: {(data.get('text') or '')[:80]}"
    text = (data.get("text") or "").strip().replace("\n", " ")
    return f"      · {text[:100]}" if text else ""


async def _print_progress(runtime: Runtime, run_id: int) -> None:
    """Фоново печатать события рана в stderr: спавн сабагентов и их шаги."""
    import sys

    def out(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    async for item in runtime.subscribe(run_id):
        if item is END_SENTINEL:
            return
        if isinstance(item, StreamGap) or item.event != "custom":
            continue
        data = item.data
        if not isinstance(data, dict):
            continue
        kind = data.get("type", "")
        if kind == "task_started":
            out(f"\n  ▶ spawn subagent [{data.get('subagent_type')}]: {data.get('description', '')}")
        elif kind == "task_running":
            line = _fmt_step(data)
            if line:
                out(line)
        elif kind.startswith("task_"):
            status = kind.removeprefix("task_")
            usage = data.get("usage") or {}
            tokens = f" · {usage.get('total_tokens')} tok" if usage.get("total_tokens") else ""
            reason = f" ({data['stop_reason']})" if data.get("stop_reason") else ""
            out(f"  ◀ subagent {status}{reason}{tokens}")


async def run(args: argparse.Namespace) -> dict[str, Any]:
    profile = build_lead_profile() if args.mode == "agent" else PIPELINE_PROFILE

    async def repository(url: str) -> dict[str, Any]:
        return await asyncio.to_thread(get_or_create_repository, url)

    commit_sha = await _resolve_commit_sha(args.repo_url)
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        runtime = Runtime(
            store=PostgresRunStore(),
            bridge=MemoryStreamBridge(),
            make_model=make_model,
            create_sandbox=create_sandbox_by_name,
            get_or_create_repository=repository,
            profile=profile,
            checkpointer=checkpointer,
        )
        await runtime.start()
        try:
            result = await runtime.submit(
                repo_url=args.repo_url,
                commit_sha=commit_sha,
                llm_api_base=args.api_base or settings.llm_api_base,
                llm_api_key=args.api_key or settings.llm_api_key,
                llm_model=args.model or settings.llm_model,
                sandbox_name=args.sandbox,
            )
            run_id = result.run["id"]
            log.info("run submitted", run_id=run_id, disposition=result.disposition.value)
            progress = asyncio.create_task(_print_progress(runtime, run_id))
            row = await runtime.wait(run_id)
            progress.cancel()
            return {
                "run_id": run_id,
                "status": row["status"],
                "commit": commit_sha,
                "report": row.get("report"),
                "error": row.get("error"),
            }
        finally:
            await runtime.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Разбор git-репозитория агентом")
    parser.add_argument("repo_url", help="URL или путь git-репозитория")
    parser.add_argument(
        "--mode",
        choices=["pipeline", "agent"],
        default="pipeline",
        help="pipeline — линейный scan→parse→report; agent — ReAct-лид с делегированием",
    )
    parser.add_argument("--model", help="имя модели (иначе LLM_MODEL из .env)")
    parser.add_argument("--api-base", help="OpenAI-совместимый endpoint")
    parser.add_argument("--api-key", help="ключ API модели")
    parser.add_argument(
        "--sandbox",
        default=DEFAULT_SANDBOX,
        help="имя песочницы из таблицы sandboxes (git|python|local|...)",
    )
    args = parser.parse_args()

    outcome = asyncio.run(run(args))
    print(json.dumps(outcome, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if outcome["status"] == "succeeded" else 1)


if __name__ == "__main__":
    main()
