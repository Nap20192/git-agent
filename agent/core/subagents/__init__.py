"""Система сабагентов: лид + делегирование через тул `task` (референс deer-flow)."""

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
