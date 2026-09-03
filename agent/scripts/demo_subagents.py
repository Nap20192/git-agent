"""Демо системы сабагентов вживую: печатает спавн, шаги и тул-вызовы."""

import asyncio
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # корень проекта в path

from langchain_core.messages import HumanMessage

from core.agents.factory import build_agent
from core.agents.features import RuntimeFeatures
from core.agents.llm import make_model
from core.subagents import SubagentCapacity, build_task_tool
from core.subagents.executor import SubagentExecutor
from core.subagents.registry import GENERAL_PURPOSE
from core.tools.sandbox import build_sandbox_tools
from core.tracing import build_tracing_callbacks
from infra.sandbox.sandboxes import create_sandbox_by_name

DEFAULT_REPO = "https://github.com/psf/requests-html"


def _p(line: str) -> None:
    print(line, flush=True)


def _fmt_step(step: dict) -> str:
    if step.get("kind") == "ai" and step.get("tool_calls"):
        calls = ", ".join(
            f"{c.get('name')}({str(c.get('args', ''))[:70]})" for c in step["tool_calls"]
        )
        return f"    → вызывает: {calls}"
    if step.get("kind") == "tool":
        return f"    ⤷ {step.get('tool_name', 'tool')} вернул: {(step.get('text') or '')[:100]}"
    text = (step.get("text") or "").strip().replace("\n", " ")
    return f"    · думает: {text[:120]}" if text else ""


async def _clone(sandbox, repo_url: str) -> None:
    d = shlex.quote(sandbox.repo_dir)
    _p(f"⌛ клонирую {repo_url} → {sandbox.repo_dir} …")
    await sandbox.run(
        f"rm -rf {d} && git clone --depth 1 {shlex.quote(repo_url)} {d}",
        timeout_seconds=180,
    )


async def demo_direct(repo_url: str) -> None:
    sandbox = await create_sandbox_by_name("git")
    try:
        await _clone(sandbox, repo_url)
        model = make_model()
        _p("\n▶ СПАВНЮ сабагента [general-purpose] напрямую\n")

        def on_step(step: dict) -> None:
            line = _fmt_step(step)
            if line:
                _p(line)

        executor = SubagentExecutor(
            GENERAL_PURPOSE, model, build_sandbox_tools(sandbox), on_step=on_step
        )
        result = await executor.arun(
            f"В директории {sandbox.repo_dir} лежит репозиторий. Перечисли все"
            " Python-файлы (используй sandbox_run с find), затем прочитай главный"
            " модуль через read_file и опиши, что он делает. Цитируй квитанции [rN].",
            task_id="demo-direct-1",
        )
        _p(f"\n◀ САБАГЕНТ завершил: status={result.status.value}")
        _p(f"  тул-квитанций собрано: {len(result.tool_receipts or [])}")
        for r in result.tool_receipts or []:
            _p(f"    [{r['id']}] {r['tool_name']} status={r['status']} bytes={r['output_bytes']}")
        _p(f"\n=== ОТЧЁТ САБАГЕНТА ===\n{result.result}")
    finally:
        await sandbox.close()


_LEAD_DELEGATING_PROMPT = """Ты — ведущий агент. Репозиторий склонирован в {repo_dir}.

ТВОЯ ЗАДАЧА — продемонстрировать делегирование. Ты ОБЯЗАН делегировать под-исследования
сабагентам через тул `task`, а не делать всё сам:
1. Сначала одним `sandbox_run` посмотри директории верхнего уровня в {repo_dir}.
2. Затем для КАЖДОЙ значимой директории/аспекта вызови `task(subagent_type="general-purpose",
   description="…", prompt="исследуй <директорию> в {repo_dir}: перечисли файлы, опиши назначение")`.
   Запусти минимум 2 сабагента.
3. Дождись их отчётов и составь ИТОГОВЫЙ обзор проекта БЕЗ вызова инструментов.

Делегируй активно — это демонстрация системы сабагентов."""


async def demo_lead(repo_url: str) -> None:
    sandbox = await create_sandbox_by_name("git")
    try:
        await _clone(sandbox, repo_url)
        model = make_model()
        capacity = SubagentCapacity()
        tools = [
            *build_sandbox_tools(sandbox),
            build_task_tool(sandbox=sandbox, model=model, capacity=capacity),
        ]
        lead = build_agent(
            model,
            tools,
            system_prompt=_LEAD_DELEGATING_PROMPT.format(repo_dir=sandbox.repo_dir),
            features=RuntimeFeatures(subagent=True, loop_detection=True, token_budget=True),
            checkpointer=False,
            name="lead",
        )
        _p("\n▶ ЗАПУСКАЮ ЛИДА (промпт форсит делегацию)\n")
        config = {"callbacks": build_tracing_callbacks(), "recursion_limit": 60}
        async for mode, chunk in lead.astream(
            {"messages": [HumanMessage(content=f"Исследуй {repo_url} через сабагентов.")]},
            config=config,
            stream_mode=["updates", "custom"],
        ):
            if mode == "custom" and isinstance(chunk, dict):
                t = chunk.get("type", "")
                if t == "task_started":
                    _p(
                        f"\n  ▶ СПАВН сабагента [{chunk.get('subagent_type')}]: {chunk.get('description')}"
                    )
                elif t == "task_running":
                    line = _fmt_step(chunk)
                    if line:
                        _p("  " + line)
                elif t.startswith("task_"):
                    _p(f"  ◀ сабагент {t.removeprefix('task_')}")
            elif mode == "updates" and isinstance(chunk, dict):
                for _node, upd in chunk.items():
                    for m in (upd or {}).get("messages", []) if isinstance(upd, dict) else []:
                        tcs = getattr(m, "tool_calls", None) or []
                        for c in tcs:
                            _p(f"ЛИД → {c.get('name')}({str(c.get('args'))[:70]})")
        _p("\n=== ГОТОВО ===")
    finally:
        await sandbox.close()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "direct"
    repo = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REPO
    if mode == "lead":
        asyncio.run(demo_lead(repo))
    else:
        asyncio.run(demo_direct(repo))


if __name__ == "__main__":
    main()
