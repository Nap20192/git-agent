"""Реестр типов сабагентов.

Из референса выброшено (по одной строке почему): поля tools/disallowed_tools —
у ребёнка ровно один toolset (sandbox-тулы), `task` отсутствует структурно;
skills — системы скиллов нет; model "inherit"|имя — фабрика принимает инстанс
модели, ребёнок наследует родительский; yaml/managed-слои и allowlist
вызывающего — один источник конфигурации, política вызывающих не нужна;
builtin `bash` с гейтингом — host-bash политики нет, sandbox_run всегда
изолирован.
"""

from __future__ import annotations

from dataclasses import dataclass

_GENERAL_PURPOSE_PROMPT = """You are a subagent: a focused worker executing ONE \
delegated task inside an isolated context. You operate on a git repository cloned \
inside a sandbox; use your tools (sandbox_run, read_file) to investigate and act.

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
5. Be dense: facts over narration; the delegating agent pays for every token."""


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
        "General-purpose research worker with sandbox tools (sandbox_run, read_file)"
        " for investigating the cloned repository. Use for self-contained research or"
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
