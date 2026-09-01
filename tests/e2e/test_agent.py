"""Smoke-тест полного прогона графа на фикстурном мини-репозитории.

Требует запущенный OpenSandbox (docker compose -f deploy/docker-compose.yml up -d).
"""

import asyncio

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from core.agents.graph import build_graph
from infra.opensandbox import create_sandbox

FIXTURE_SETUP = (
    "mkdir /fixture && cd /fixture && git init -q && "
    "git config user.email t@t.t && git config user.name t && "
    "printf 'import os\\n\\nclass App:\\n    pass\\n\\ndef main():\\n    pass\\n' > app.py && "
    "printf 'requests>=2\\n' > requirements.txt && "
    "printf '# Demo\\n' > README.md && "
    "git add -A && git commit -qm init"
)


async def _run() -> dict:
    sandbox = await create_sandbox()
    try:
        await sandbox.run(FIXTURE_SETUP)
        model = GenericFakeChatModel(messages=iter([AIMessage(content="Учебный демо-проект.")]))
        graph = build_graph(sandbox, model)
        final = await graph.ainvoke({"repo_url": "/fixture"})
        return final["report"]
    finally:
        await sandbox.close()


def test_full_run_on_fixture_repo():
    report = _report()
    assert "error" not in report
    assert report["commit"]
    assert report["description"] == "Учебный демо-проект."
    assert report["dependencies"] == ["requests>=2"]
    assert "README.md" in report["structure"]["key_files"]
    (module,) = [m for m in report["modules"] if m["path"] == "app.py"]
    assert module["classes"] == ["App"]
    assert module["functions"] == ["main"]


def _report() -> dict:
    return asyncio.run(_run())
