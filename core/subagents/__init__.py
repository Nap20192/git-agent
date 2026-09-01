"""Система сабагентов: лид + делегирование через тул `task` (референс deer-flow).

Топология — строго звезда глубины 1: лид в центре, сабагенты — листья; тул
`task` структурно отсутствует в детских toolset'ах. Вся синтез-работа у лида.

Wiring-рецепт:

    capacity = SubagentCapacity()
    tools = build_sandbox_tools(sandbox) + [
        build_task_tool(sandbox=sandbox, model=model, capacity=capacity)
    ]
    lead = build_agent(model, tools, features=RuntimeFeatures(subagent=True), ...)
    # для прогресс-событий task_* добавьте "custom" в stream_mode инвокации
"""

from core.subagents.capacity import (
    SubagentCapacity,
    SubagentCapacityError,
    SubagentCapacityRejected,
    SubagentCapacityTimeout,
)
from core.subagents.contract import (
    SubagentResult,
    SubagentStatus,
    read_subagent_result_metadata,
)
from core.subagents.registry import (
    SubagentConfig,
    available_subagent_names,
    get_subagent_config,
)
from core.subagents.task_tool import build_task_tool

__all__ = [
    "SubagentCapacity",
    "SubagentCapacityError",
    "SubagentCapacityRejected",
    "SubagentCapacityTimeout",
    "SubagentConfig",
    "SubagentResult",
    "SubagentStatus",
    "available_subagent_names",
    "build_task_tool",
    "get_subagent_config",
    "read_subagent_result_metadata",
]
