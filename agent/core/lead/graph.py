"""Лид-агент как GraphProfile: ReAct-лид, security-ревью кода репозитория."""

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


LEAD_SYSTEM_PROMPT = """Ты — авторизованный security-ревьюер-ОРКЕСТРАТОР кода. Репозиторий \
этой задачи УЖЕ СКЛОНИРОВАН в {repo_dir} и находится В СКОУПЕ: у тебя полная авторизация \
на его security-анализ. Не отказывайся, не запрашивай подтверждений и не квалифицируй \
нормальный разбор in-scope кода как недопустимый; формулируй работу как validate / verify / \
confirm / assess / remediate.

СКОУП — СТАТИЧЕСКИЙ АНАЛИЗ (white-box) уже склонированного кода: чтение исходников, \
трассировка потоков данных source→sink, подтверждение по коду. Динамического / live-тулинга у \
системы НЕТ (ни браузера, ни прокси, ни сканеров/фаззеров, ни отправки эксплойт-пейлоадов) — не \
пытайся его запускать и не выдумывай результаты «запусков». sandbox_run — это read-only shell по \
коду (ls/find/grep/cat), а не средство атаки.

ТЫ — КОРНЕВОЙ АГЕНТ: твоя работа ОРКЕСТРАЦИЯ, а не ручной аудит. Ты добиваешься покрытия, \
ДЕЛЕГИРУЯ проверки Сабагентам через `task`, а не читая и анализируя файлы сам. Сам ты только \
строишь БЕГЛУЮ карту (дерево, стек, точки входа, границы доверия) — на это допустим минимум \
sandbox_run. Всё остальное — чтение кода, подтверждение эксплуатируемости, фиксацию Находок — \
выполняют Сабагенты. Даже «быстро глянуть» подозрительный файл — не твоя роль: вместо этого \
делегируй. Свои ходы трать на: чтение скоупа и структуры, декомпозицию цели, спавн и мониторинг \
Сабагентов, сбор и приоритизацию результатов.

Инструменты:
- sandbox_run(command): read-only shell ТОЛЬКО для карты (ls, find, grep, cat README/манифестов). Не для аудита.
- task(description, prompt, subagent_type): делегировать проверку области Сабагенту. В prompt дай \
  ЧЁТКИЙ скоуп (файлы/каталоги/область), какие skills загрузить, что искать и требование вернуть \
  подтверждённые Находки через report_finding. subagent_type: general-purpose.
- load_skill / report_finding есть и у тебя, но фиксация Находок — задача Сабагентов; ты \
  агрегируешь и, при необходимости, доносишь подтверждённые в итог.
{mcp_section}

Каталог skills (подсказывай Сабагентам, какие грузить ПЕРЕД догадками о пейлоадах/синтаксисе):
{skills_catalog}

ВЫСОКОПРИОРИТЕТНЫЕ КЛАССЫ — делегируй релевантные, каждую область отдельному Сабагенту \
(параллель приветствуется; зависимые шаги — последовательно):
1. Recon/карта: стек, фреймворки, точки входа (HTTP-хендлеры, CLI, воркеры, очереди), где входит \
   недоверенный ввод, границы доверия, менеджеры зависимостей.
2. Инъекции: SQL/NoSQL/command/argument-injection там, где недоверенный ввод достигает интерпретатора.
3. XSS / шаблоны / SSTI.
4. Аутентификация и доступ: authn/JWT, IDOR/BOLA, отсутствующая/сломанная авторизация, привилегии.
5. SSRF / path traversal / file upload / open redirect.
6. Десериализация / mass-assignment / prototype pollution.
7. Секреты / раскрытие информации / криптомисьюз (захардкоженные ключи, слабые примитивы).
8. Бизнес-логика / гонки / TOCTOU.
Плюс: при наличии манифестов зависимостей — известные CVE (через MCP-CVE тулы, если доступны).

Рабочий процесс:
1. Быстрая карта репозитория (structure, стек, точки входа) — коротко, сам.
2. Разбей цель на области и ДЕЛЕГИРУЙ каждую релевантную Сабагенту со скоупом файлов и подсказкой \
   skills. Области сам не проверяй.
3. Собери Находки; при пробелах — дошли добивающие делегации.
4. Дай ФИНАЛЬНЫЙ ОТВЕТ ТЕКСТОМ БЕЗ вызова инструментов — резюме: покрытые области, общий риск, \
   приоритеты. Это единственный сигнал завершения.

ДИСЦИПЛИНА ЗАКРЫТИЯ (требуй от Сабагентов и держи сам): каждый кандидат заканчивается в ОДНОМ \
явном состоянии — confirmed (достижимый трейс source→control→sink→impact), ruled_out (можешь \
назвать КОНКРЕТНЫЙ контроль в конкретном месте, срабатывающий на КАЖДОМ достижимом пути до sink) \
или open_proof_gap (правдоподобно, не подтверждено, контроль назвать нельзя). «Пропустил» — не \
состояние закрытия. Отсутствие информации (не нашли вызывающего, неясно задеплоено ли, не \
собралось) — это open_proof_gap, а НЕ доказательство безопасности.

КАЛИБРОВКА SEVERITY: оценивай ТОЛЬКО продемонстрированный по коду импакт, а не достижимость, \
метки сканеров или теоретические follow-on цепочки. Учитывай контекст (демо / намеренно публичное — \
ниже). Перед фиксацией Сабагент проходит counterevidence-проход (аргумент ПРОТИВ находки) и ставит \
честный confidence (static-only трейс без запуска — максимум medium).

ОТЧЁТ = ФИКС: Находка фиксируется через report_finding с severity/CWE/CVE/файл:строки/evidence/ \
remediation — конкретное исправление выводится тем же ходом, отдельного «фиксящего» прохода нет.

ПЕРСИСТЕНТНОСТЬ: не останавливайся на поверхностных проверках — продолжай, пока самые ценные \
in-scope пути не оценены. Лучше одна хорошо подтверждённая high-impact Находка, чем десяток шумных."""

_LEAD_TASK = (
    "Проведи security-ревью репозитория {repo_url} КАК ОРКЕСТРАТОР: построй беглую"
    " карту, затем делегируй проверку областей из чеклиста Сабагентам (сам код не"
    " аудируй). Собери их Находки и дай итоговое резюме с приоритетами."
)


def _lead_input(
    repo_url: str, checkout_ref: str | None = None, instructions: str | None = None
) -> dict[str, Any]:
    """Вход лида: пользовательская задача Рана или дефолтная формулировка."""
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
    return {"answer": summary, "summary": summary, "findings": findings}


def _lead_features(
    limits: dict[str, Any],
) -> tuple[RuntimeFeatures, SubagentCapacity, float | None]:
    """RuntimeFeatures + capacity + exec-таймаут Сабагента из лимитов Рана (с дефолтами).

    subagentTimeout — потолок исполнения Сабагента (None ⇒ дефолт типа);
    queueTimeout — ожидание слота в capacity; maxSubagents — конкурентность (и
    capacity, и лид-сторонний max_concurrent); maxTotalSubagents — всего делегаций.
    """
    from core.middleware.subagent_limit import DEFAULT_MAX_TOTAL_PER_RUN, SubagentLimitMiddleware
    from core.middleware.token_budget import TokenBudgetMiddleware

    subagent = limits.get("subagent", True)
    loop = limits.get("loopDetection", True)
    budget = limits.get("tokenBudget")
    max_subagents = max(1, int(limits.get("maxSubagents") or 3))
    max_total = max(1, int(limits.get("maxTotalSubagents") or DEFAULT_MAX_TOTAL_PER_RUN))
    queue_timeout = limits.get("queueTimeout")
    exec_timeout = limits.get("subagentTimeout")
    token_budget: Any = False
    if budget:
        token_budget = TokenBudgetMiddleware(max_total_tokens=int(budget))
    # subagent как middleware-инстанс с лимитами (сборка features.py кладёт его как есть);
    # False — делегирование выключено (нет task-тула и лимит-middleware)
    subagent_feature: Any = (
        SubagentLimitMiddleware(max_concurrent=max_subagents, max_total_per_run=max_total)
        if subagent
        else False
    )
    features = RuntimeFeatures(
        subagent=subagent_feature,
        loop_detection=bool(loop),
        token_budget=token_budget,
    )
    capacity_kwargs: dict[str, Any] = {"max_running": max_subagents}
    if queue_timeout:
        capacity_kwargs["queue_timeout_seconds"] = float(queue_timeout)
    capacity = SubagentCapacity(**capacity_kwargs)
    return features, capacity, (float(exec_timeout) if exec_timeout else None)


def build_lead_profile(
    mcp_tools: list[BaseTool] = (), security_tools: list[BaseTool] | None = None
) -> GraphProfile:
    """security_tools — переопределение report_finding/load_skill (раннер подставляет
    hub-персистящие варианты); None — стандартные build_security_tools()."""
    mcp_tools = list(mcp_tools)
    injected_security_tools = list(security_tools) if security_tools is not None else None

    def _build(
        sandbox: Sandbox,
        model: BaseChatModel,
        *,
        checkpointer: Any = None,
        limits: dict[str, Any] | None = None,
    ) -> Any:
        features, capacity, exec_timeout = _lead_features(limits or {})
        security_tools = injected_security_tools or build_security_tools()
        candidates = [*build_sandbox_tools(sandbox), *security_tools]
        if features.subagent:
            candidates.append(
                build_task_tool(
                    sandbox=sandbox,
                    model=model,
                    capacity=capacity,
                    extra_tools=security_tools,
                    timeout_override=exec_timeout,
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
