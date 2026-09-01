"""Лид-агент как GraphProfile: ReAct-лид, security-ревью кода репозитория.

Отличие от линейного pipeline: лид сам решает, что читать и когда делегировать;
вход — задача текстом, отчёт — резюме + структурированные Находки. В security-
режиме у него есть report_finding, load_skill (skills-справочник) и — при
подключённых MCP-серверах — их тулы за deferred-каталогом (tool_search).
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool

from core.agents.factory import build_agent
from core.agents.features import RuntimeFeatures
from core.agents.findings import build_security_tools, collect_findings
from core.ports import Sandbox
from core.repo import prepare_repo
from core.runtime.profile import GraphProfile
from core.skills import available_skills
from core.subagents import SubagentCapacity, build_task_tool
from core.tools import assemble_deferred_tools, get_deferred_tools_prompt_section
from core.tools.sandbox import build_sandbox_tools

LEAD_MAX_TURNS = 100000


def _skills_catalog() -> str:
    by_cat: dict[str, list[str]] = {}
    for skill in available_skills():
        by_cat.setdefault(skill["category"], []).append(skill["name"])
    return "\n".join(
        f"- {cat}: {', '.join(sorted(names))}" for cat, names in sorted(by_cat.items())
    )


LEAD_SYSTEM_PROMPT = """Ты — авторизованный security-ревьюер кода. Репозиторий УЖЕ \
СКЛОНИРОВАН в {repo_dir} внутри изолированной песочницы (только чтение исходников, \
без запуска). Твоя задача — найти реальные уязвимости в КОДЕ и составить отчёт \
из подтверждённых Находок.

Инструменты:
- sandbox_run(command): shell в песочнице (find, grep, cat, git). Начни с обзора дерева.
- read_file(path): прочитать файл (путь внутри {repo_dir}).
- load_skill(skills): подгрузить методичку по классу уязвимости/технологии ПЕРЕД \
  проверкой (точный синтаксис, места, признаки). Максимум 5 за раз.
- report_finding(...): зафиксировать ПОДТВЕРЖДЁННУЮ уязвимость (severity, файл/строки, \
  описание, impact, evidence-цитата кода, cwe, remediation). Только по реально \
  прочитанному коду, не по догадке.
- task(...): делегировать под-проверку сабагенту (тяжёлое чтение, независимые ветки).
{mcp_section}

Каталог skills (загружай релевантные через load_skill):
{skills_catalog}

Рабочий процесс:
1. Осмотри структуру, стек, точки входа, обработку недоверенного ввода, зависимости.
2. По каждому подозрению: подгрузи skill, прочитай код, подтверди эксплуатируемость.
3. Фиксируй КАЖДУЮ подтверждённую уязвимость через report_finding с severity и evidence.
4. Дай ФИНАЛЬНЫЙ ОТВЕТ ТЕКСТОМ БЕЗ вызова инструментов — краткое резюме ревью \
   (это единственный сигнал завершения). Находки уже зафиксированы инструментом.

ВАЖНО: severity калибруй консервативно; не выдумывай уязвимости ради количества. \
Лучше короткий честный отчёт, чем ложные срабатывания."""

_LEAD_TASK = (
    "Проведи security-ревью кода репозитория {repo_url} (склонирован в рабочую"
    " директорию, путь — в системном промпте). Найди и зафиксируй реальные"
    " уязвимости. Начни с осмотра рабочей директории."
)


def _lead_input(
    repo_url: str, checkout_ref: str | None = None, instructions: str | None = None
) -> dict[str, Any]:
    """Вход лида: пользовательская задача Рана или дефолтная формулировка.

    В instructions поддерживается плейсхолдер {repo_url}; .replace, не .format —
    произвольные фигурные скобки в тексте пользователя не должны ронять запуск.
    """
    if instructions and instructions.strip():
        text = instructions.replace("{repo_url}", repo_url)
    else:
        text = _LEAD_TASK.format(repo_url=repo_url)
    return {"messages": [HumanMessage(content=text)]}


def _final_answer(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = message.text if isinstance(message.text, str) else str(message.content)
            if text and text.strip():
                return text.strip()
    return ""


def _lead_report(values: dict[str, Any]) -> dict[str, Any] | None:
    messages = (values or {}).get("messages") or []
    findings = collect_findings(messages)
    summary = _final_answer(messages)
    if not summary and not findings:
        return {"answer": "", "findings": [], "error": "lead produced no final answer"}
    # answer — совместимость (proseview/старый UI); summary — то же, findings — новое
    return {"answer": summary, "summary": summary, "findings": findings}


def _lead_features(limits: dict[str, Any]) -> tuple[RuntimeFeatures, SubagentCapacity]:
    """RuntimeFeatures + capacity из пользовательских лимитов Рана (с дефолтами)."""
    from core.middleware.token_budget import TokenBudgetMiddleware

    subagent = limits.get("subagent", True)
    loop = limits.get("loopDetection", True)
    budget = limits.get("tokenBudget")
    max_subagents = int(limits.get("maxSubagents") or 3)
    token_budget: Any = True
    if budget:  # число > 0 → конкретный бюджет; иначе дефолтный middleware
        token_budget = TokenBudgetMiddleware(max_total_tokens=int(budget))
    features = RuntimeFeatures(
        subagent=bool(subagent),
        loop_detection=bool(loop),
        token_budget=token_budget,
    )
    capacity = SubagentCapacity(max_running=max(1, max_subagents))
    return features, capacity


def build_lead_profile(mcp_tools: list[BaseTool] = ()) -> GraphProfile:
    mcp_tools = list(mcp_tools)

    def _build(
        sandbox: Sandbox,
        model: BaseChatModel,
        *,
        checkpointer: Any = None,
        limits: dict[str, Any] | None = None,
    ) -> Any:
        features, capacity = _lead_features(limits or {})
        security_tools = build_security_tools()
        candidates = [*build_sandbox_tools(sandbox), *security_tools]
        # task-тул только если делегирование включено; детям — load_skill и
        # report_finding (их Находки собираются из хода Сабагента в сводный отчёт)
        if features.subagent:
            candidates.append(
                build_task_tool(
                    sandbox=sandbox, model=model, capacity=capacity, extra_tools=security_tools
                )
            )
        candidates.extend(mcp_tools)
        tools, setup = assemble_deferred_tools(candidates, enabled=bool(mcp_tools))
        mcp_section = ""
        if setup.deferred_names:
            mcp_section = (
                "\n- MCP-тулы (CVE-интеллект и др.): их схемы отложены; найди нужный"
                " тул через tool_search и вызови.\n"
                + get_deferred_tools_prompt_section(deferred_names=setup.deferred_names)
            )
        prompt = LEAD_SYSTEM_PROMPT.format(
            repo_dir=sandbox.repo_dir,
            skills_catalog=_skills_catalog(),
            mcp_section=mcp_section,
        )
        return build_agent(
            model,
            tools,
            system_prompt=prompt,
            features=features,
            checkpointer=checkpointer,
            name="lead",
        )

    return GraphProfile(
        build=_build,
        prepare=prepare_repo,
        make_input=_lead_input,
        extract_report=_lead_report,
        stream_modes=["updates", "custom"],
        run_config={"recursion_limit": LEAD_MAX_TURNS},
    )
