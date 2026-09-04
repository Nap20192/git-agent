"""Реестр типов сабагентов."""

from __future__ import annotations

from dataclasses import dataclass

_GENERAL_PURPOSE_PROMPT = """You are a subagent: a focused worker executing ONE \
delegated task inside an isolated context. You operate on a git repository cloned \
inside a sandbox; use your tools to investigate: list_dir, read_file (paged, with \
line numbers), grep_code (ripgrep with context), git_diff / git_blame, and sandbox_run \
(shell; analyzers like semgrep/bandit may be present — check `command -v` first). \
`web_search(query)` (when available) finds external facts — advisories, CVE/GHSA, known \
vulnerabilities of a dependency version; `browse(url)` fetches an external web page as text — use it for external facts only \
(advisories, CVE/NVD/GHSA, dependency docs); grep/read the repository code first, never \
browse the repo itself.

Rules:
- You are a subagent — the `task` tool is NOT available to you; never attempt to \
delegate further. Do all the work yourself.
- Stay strictly within the delegated task. Do not expand scope.
- Your context is disposable; only your final report survives. Make it \
self-contained: the delegating agent sees nothing else.

Final report contract (5 points):
1. Answer the delegated question directly, first.
2. Cite receipt ids for every action claim (see report_contract below).
3. Attach verifiable handles (absolute paths, exact commands) to findings.
4. List what failed or remains uncertain.
5. Be dense: facts over narration; the delegating agent pays for every token.

Confirmed vulnerabilities go through `report_finding` with ALL fields you know: title, \
description (source→sink trace), impact, confidence (high/medium/low), category, severity, \
cwe/cve, file (required) + start_line/end_line, evidence, remediation, references (URLs). \
Never guess or pass blame/author/commit — the system resolves it from file and lines."""


@dataclass(frozen=True)
class SubagentConfig:
    name: str
    description: str  # модель-видимый текст роутинга
    system_prompt: str
    max_turns: int = 50
    timeout_seconds: float = 600.0


GENERAL_PURPOSE = SubagentConfig(
    name="general-purpose",
    description=(
        "General-purpose research worker with sandbox tools (list_dir, read_file,"
        " grep_code, git_diff, git_blame, sandbox_run, browse, web_search) for investigating the cloned repository. Use for self-contained research or"
        " analysis whose intermediate context you do not need — only its report"
        " returns. Do NOT use merely because work is complex or multi-step."
    ),
    system_prompt=_GENERAL_PURPOSE_PROMPT,
)

BUILTIN_SUBAGENTS: dict[str, SubagentConfig] = {GENERAL_PURPOSE.name: GENERAL_PURPOSE}


def get_subagent_config(name: str) -> SubagentConfig | None:
    return BUILTIN_SUBAGENTS.get(name)


def available_subagent_names() -> list[str]:
    return sorted(BUILTIN_SUBAGENTS)


def resolve_subagent_config(name: str) -> tuple[SubagentConfig | None, str | None]:
    """(конфиг, замечание) по имени типа, как его написала модель. Точное имя —
    без замечания; иначе нормализация (регистр, `_`/пробел → `-`) и префикс
    («general» → «general-purpose»); единственный зарегистрированный тип берётся
    при любом имени. Локальные модели часто пишут тип по памяти — падать из-за
    этого ходом дороже, чем подставить и сказать об этом в результате."""
    if (exact := BUILTIN_SUBAGENTS.get(name)) is not None:
        return exact, None
    norm = (name or "").strip().lower().replace("_", "-").replace(" ", "-")
    candidates = [
        n for n in BUILTIN_SUBAGENTS if n == norm or n.startswith(norm) or norm.startswith(n)
    ]
    if not candidates and len(BUILTIN_SUBAGENTS) == 1:
        candidates = list(BUILTIN_SUBAGENTS)
    if len(candidates) != 1:
        return None, None
    chosen = candidates[0]
    return BUILTIN_SUBAGENTS[chosen], f"subagent_type '{name}' resolved to '{chosen}'"
