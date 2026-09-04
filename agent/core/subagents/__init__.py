"""Система сабагентов (референс deer-flow). Вход — тул `task` из core/tools/delegation."""

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
    resolve_subagent_config,
)

__all__ = [
    "SubagentCapacity",
    "SubagentCapacityError",
    "SubagentCapacityRejected",
    "SubagentCapacityTimeout",
    "SubagentConfig",
    "SubagentResult",
    "SubagentStatus",
    "available_subagent_names",
    "get_subagent_config",
    "read_subagent_result_metadata",
    "resolve_subagent_config",
]
