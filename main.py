"""CLI: uv run main.py <repo-url> [--model ... --api-base ... --api-key ...]"""

import argparse
import asyncio
import json
from typing import Any

from core.agents.graph import build_graph
from core.agents.llm import make_model
from core.tracing import build_tracing_callbacks, inject_langfuse_metadata
from infra.sandboxes import DEFAULT_SANDBOX, create_sandbox_by_name
from pkg.logger import get_logger

log = get_logger("main")


async def run(args: argparse.Namespace) -> dict[str, Any]:
    model = make_model(model=args.model, api_base=args.api_base, api_key=args.api_key)
    sandbox = await create_sandbox_by_name(args.sandbox)
    try:
        graph = build_graph(sandbox, model)
        config: dict[str, Any] = {"callbacks": build_tracing_callbacks()}
        inject_langfuse_metadata(
            config, thread_id=None, model_name=args.model, environment="cli"
        )
        final = await graph.ainvoke({"repo_url": args.repo_url}, config=config)
        return final["report"]
    finally:
        await sandbox.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Разбор git-репозитория агентом")
    parser.add_argument("repo_url", help="URL или путь git-репозитория")
    parser.add_argument("--model", help="имя модели (иначе LLM_MODEL из .env)")
    parser.add_argument("--api-base", help="OpenAI-совместимый endpoint")
    parser.add_argument("--api-key", help="ключ API модели")
    parser.add_argument(
        "--sandbox",
        default=DEFAULT_SANDBOX,
        help="имя песочницы из таблицы sandboxes (git|python|local|...)",
    )
    args = parser.parse_args()

    report = asyncio.run(run(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if "error" in report else 0)


if __name__ == "__main__":
    main()
