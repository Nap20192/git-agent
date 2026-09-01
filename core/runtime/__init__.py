"""Runtime — durable-исполнение Ранов: «ран — это ресурс, а не запрос».

Адаптация архитектуры deer-flow runtime: admission через CAS на строке runs,
lease+heartbeat с fail-closed fence, orphan recovery, реплеябельный стрим
с честными пробелами, идемпотентная финализация.
"""

from core.runtime.bridge import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    MemoryStreamBridge,
    StreamEvent,
    StreamGap,
    StreamItem,
)
from core.runtime.manager import RunManager
from core.runtime.runtime import Runtime
from core.runtime.schemas import (
    CancelOutcome,
    ConflictError,
    RunStartOutcome,
    RunStatus,
    SubmitDisposition,
    SubmitResult,
)
from core.runtime.store_memory import MemoryRunStore

__all__ = [
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "CancelOutcome",
    "ConflictError",
    "MemoryRunStore",
    "MemoryStreamBridge",
    "RunManager",
    "RunStartOutcome",
    "RunStatus",
    "Runtime",
    "StreamEvent",
    "StreamGap",
    "StreamItem",
    "SubmitDisposition",
    "SubmitResult",
]
