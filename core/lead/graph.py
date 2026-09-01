"""Лид-агент как GraphProfile: ReAct-лид с sandbox-тулами + делегированием.

Отличие от линейного pipeline: лид сам решает, что читать и когда делегировать
исследование сабагентам; вход — задача текстом, отчёт — финальный ответ модели.
Подключается в рантайм как профиль, воркер не меняется.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from core.agents.factory import build_agent
from core.agents.features import RuntimeFeatures
from core.ports import Sandbox
from core.repo import prepare_repo
from core.runtime.profile import GraphProfile
from core.subagents import SubagentCapacity, build_task_tool
from core.tools.sandbox import build_sandbox_tools

LEAD_MAX_TURNS = 100000

LEAD_SYSTEM_PROMPT = """Ты — ведущий агент, который исследует git-репозиторий и \
составляет о нём структурированный отчёт. Репозиторий УЖЕ СКЛОНИРОВАН в директорию \
{repo_dir} внутри песочницы — работай там, повторно клонировать НЕ нужно.

Инструменты:
- sandbox_run(command): shell-команда в песочнице (git, find, cat, grep, ls).
  Начни с `ls -la {repo_dir}` и осмотра дерева файлов.
- read_file(path): прочитать файл (абсолютный путь внутри {repo_dir}).
- task(...): делегировать под-исследование сабагенту с изолированным контекстом.
  Делегируй ТОЛЬКО когда это явно выгодно (тяжёлое чтение многих файлов, независимые
  ветки анализа), не ради каждого шага.

Рабочий процесс (уложись примерно в 15 ходов):
1. Осмотри структуру {repo_dir}: дерево файлов, языки, README, манифесты зависимостей.
2. Прочитай ключевые файлы, чтобы понять назначение и устройство проекта.
3. Дай ФИНАЛЬНЫЙ ОТВЕТ — структурированный отчёт: назначение, стек, структура,
   ключевые модули, зависимости, точки входа. Опирайся на прочитанное.

ВАЖНО: когда данных достаточно, дай финальный ответ ТЕКСТОМ БЕЗ вызова инструментов —
это единственный сигнал завершения. Не зови инструменты бесконечно; лучше короткий
честный отчёт, чем ещё один tool-вызов."""

_LEAD_TASK = (
    "Исследуй репозиторий {repo_url} (склонирован в рабочую директорию, путь — в"
    " системном промпте) и составь структурированный отчёт: что это за проект, из"
    " чего состоит, как устроен. Начни с осмотра рабочей директории."
)


def _lead_report(values: dict[str, Any]) -> dict[str, Any] | None:
    messages = (values or {}).get("messages") or []
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = message.text if isinstance(message.text, str) else str(message.content)
            if text and text.strip():
                return {"answer": text}
    return {"answer": "", "error": "lead produced no final answer"}


def build_lead_profile() -> GraphProfile:
    def _build(sandbox: Sandbox, model: BaseChatModel, *, checkpointer: Any = None) -> Any:
        capacity = SubagentCapacity()
        tools = [
            *build_sandbox_tools(sandbox),
            build_task_tool(sandbox=sandbox, model=model, capacity=capacity),
        ]
        return build_agent(
            model,
            tools,
            system_prompt=LEAD_SYSTEM_PROMPT.format(repo_dir=sandbox.repo_dir),
            features=RuntimeFeatures(subagent=True, loop_detection=True, token_budget=True),
            checkpointer=checkpointer,
            name="lead",
        )

    return GraphProfile(
        build=_build,
        prepare=prepare_repo,
        make_input=lambda repo_url, checkout_ref=None: {
            "messages": [HumanMessage(content=_LEAD_TASK.format(repo_url=repo_url))]
        },
        extract_report=_lead_report,
        # custom — прогресс-события сабагентов (task_*); updates — ходы графа
        stream_modes=["updates", "custom"],
        run_config={"recursion_limit": LEAD_MAX_TURNS},
    )
