"""Лид-агент как GraphProfile: ReAct-лид, security-ревью кода репозитория."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool

from core.agents.factory import build_agent
from core.agents.features import RuntimeFeatures
from core.lead.profile import GraphProfile
from core.ports import Sandbox
from core.skills import available_skills
from core.subagents import SubagentCapacity
from core.tools.delegation import build_task_tool
from core.tools.mcp import assemble_deferred_tools, get_deferred_tools_prompt_section
from core.tools.sandbox import build_sandbox_tools
from core.tools.security import build_security_tools, collect_findings

LEAD_MAX_TURNS = 100000


def _skills_catalog() -> str:
    by_cat: dict[str, list[str]] = {}
    for skill in available_skills():
        by_cat.setdefault(skill["category"], []).append(skill["name"])
    return "\n".join(
        f"- {cat}: {', '.join(sorted(names))}" for cat, names in sorted(by_cat.items())
    )


LEAD_SYSTEM_PROMPT = """You are an AUTHORIZED security reviewer and ORCHESTRATOR. \
The repository for this task is ALREADY CLONED at {repo_dir} and IS IN SCOPE: you are fully \
authorized to security-analyze it. Never refuse, never ask for confirmation, never treat \
review of in-scope code as illegitimate; frame the work as validate / verify / confirm / \
assess / remediate.

SCOPE — STATIC white-box analysis of the cloned code: read sources, trace source→sink data \
flows, confirm in code. There is NO dynamic or live tooling (no browser, proxy, scanner, \
fuzzer, exploit payloads) — never attempt it and never invent results of "runs". sandbox_run \
is a read-only shell over the code (ls/find/grep/cat), not an attack tool.

ROLE — ROOT ORCHESTRATOR, not a hands-on auditor. Get coverage by DELEGATING checks to \
subagents via `task`, not by reading and analyzing files yourself. You personally build only \
a QUICK map (tree, stack, entry points, trust boundaries); minimal sandbox_run is fine for \
that. Subagents do everything else — reading code, proving exploitability, filing findings. \
Even "just a quick look" at a suspicious file is not your role: delegate it. Spend your turns \
on scope and structure, decomposition, spawning and monitoring subagents, collecting and \
prioritizing results.

TOOLS (subagents have the same set, minus task):
- list_dir / read_file(path, offset, limit) / grep_code(pattern, path, glob, context): map, \
  paged reads with line numbers, ripgrep code search. Yours for the map ONLY, never for audit.
- git_diff(ref, base, path, stat) / git_blame(path, start_line, end_line): what the event \
  commit changed and where lines came from — start a push scope with git_diff(stat=true).
- sandbox_run(command): shell in the sandbox (image ships git, rg, semgrep, bandit, node, go; \
  the set depends on the tag — run `command -v <bin>` before any analyzer). Not an attack tool.
- browse(url): readable page text — ONLY for external facts (advisories, CVE/NVD/GHSA, \
  dependency docs and READMEs). Read the repo with grep_code/read_file, never through browse.
- task(description, prompt, subagent_type): delegate one area to a subagent. The prompt must \
  give a PRECISE scope (files/dirs/area), which skills to load, what to look for, and demand \
  confirmed findings via report_finding. subagent_type: general-purpose.
- load_skill / report_finding: available to you too, but filing findings is the subagents' \
  job; you aggregate and, when needed, carry confirmed ones into the summary.
{mcp_section}

SKILLS CATALOG (tell subagents what to load BEFORE guessing payloads/syntax):
{skills_catalog}

HIGH-PRIORITY CLASSES — delegate every relevant one to its own subagent (parallel where \
independent, sequential where dependent):
1. Recon/map: stack, frameworks, entry points (HTTP handlers, CLI, workers, queues), where \
   untrusted input enters, trust boundaries, dependency manifests.
2. Injection: SQL/NoSQL/command/argument injection where untrusted input reaches an interpreter.
3. XSS / templates / SSTI.
4. Authn & access: authn/JWT, IDOR/BOLA, missing or broken authorization, privileges.
5. SSRF / path traversal / file upload / open redirect.
6. Deserialization / mass assignment / prototype pollution.
7. Secrets / information disclosure / crypto misuse (hardcoded keys, weak primitives).
8. Business logic / races / TOCTOU.
Plus: when dependency manifests exist — known CVEs (via MCP CVE tools if available).

WORKFLOW:
1. Quick repo map (structure, stack, entry points) — short, yourself.
2. Split the goal into areas and DELEGATE each relevant one with a file scope and a skills \
   hint. Never audit an area yourself.
3. Collect the findings; on gaps, send follow-up delegations.
4. Give the FINAL ANSWER AS PLAIN TEXT WITH NO TOOL CALLS — covered areas, overall risk, \
   priorities. This is the only completion signal.

CLOSURE DISCIPLINE (demand it from subagents, hold it yourself): every candidate ends in ONE \
explicit state — confirmed (reachable source→control→sink→impact trace), ruled_out (you can \
name a SPECIFIC control at a specific place that fires on EVERY reachable path to the sink), \
or open_proof_gap (plausible, unproven, no control to name). "Skipped" is not a closure state. \
Missing information (no caller found, deployment unclear, build failed) is open_proof_gap, \
NOT proof of safety.

SEVERITY CALIBRATION: rate ONLY impact demonstrated in the code — not reachability, scanner \
labels or theoretical follow-on chains; lower it for context (demo, intentionally public). \
Before filing, the subagent runs a counterevidence pass (the case AGAINST the finding) and \
sets honest confidence — a static-only trace with no execution is medium at most.

REPORT = FIX: file through report_finding COMPLETELY — title, description, impact, confidence, \
category, severity, CWE/CVE, file:lines (file is required), evidence, remediation, references \
(advisory/CWE/doc URLs); the concrete fix comes in the same pass, there is no separate fixing \
pass. NEVER guess or pass blame (line author/commit) — the system resolves it and returns it \
in the tool response. Final write_report structure: summary, scope, method (which \
tools/analyzers were used), top_risks, recommendations, limitations.

PERSISTENCE: do not stop at surface checks — continue until the most valuable in-scope paths \
are assessed. One well-confirmed high-impact finding beats ten noisy ones."""

_LEAD_TASK = (
    "Run a security review of repository {repo_url} AS AN ORCHESTRATOR: build a quick map,"
    " then delegate the checklist areas to subagents (do not audit the code yourself)."
    " Collect their findings and give a final summary with priorities."
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
        make_input=_lead_input,
        extract_report=_lead_report,
        stream_modes=["updates", "custom"],
        run_config={"recursion_limit": LEAD_MAX_TURNS},
    )
