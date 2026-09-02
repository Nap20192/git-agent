"""Контракт статусов/результата сабагента (референс: deerflow/subagents/status_contract.py)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal, NotRequired, TypedDict

SUBAGENT_STATUS_KEY = "subagent_status"
SUBAGENT_STOP_REASON_KEY = "subagent_stop_reason"
SUBAGENT_ERROR_KEY = "subagent_error"
SUBAGENT_RESULT_BRIEF_KEY = "subagent_result_brief"
SUBAGENT_RESULT_SHA256_KEY = "subagent_result_sha256"
SUBAGENT_MODEL_NAME_KEY = "subagent_model_name"
SUBAGENT_TOKEN_USAGE_KEY = "subagent_token_usage"
SUBAGENT_TOOL_RECEIPTS_KEY = "subagent_tool_receipts"
SUBAGENT_RECEIPT_VERDICT_KEY = "subagent_receipt_verdict"
SUBAGENT_METADATA_TEXT_MAX_CHARS = 2000

_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")

SubagentStatusValue = Literal["completed", "failed", "cancelled", "timed_out"]
SUBAGENT_STATUS_VALUES: tuple[SubagentStatusValue, ...] = (
    "completed",
    "failed",
    "cancelled",
    "timed_out",
)
# polling_timed_out из референса отсутствует: поллинга нет, ребёнок ждётся inline.

SubagentStopReasonValue = Literal["token_capped", "turn_capped", "loop_capped"]
SUBAGENT_STOP_REASON_VALUES: tuple[SubagentStopReasonValue, ...] = (
    "token_capped",
    "turn_capped",
    "loop_capped",
)
_STOP_REASON_LABELS = {
    "token_capped": "token budget",
    "turn_capped": "turn budget",
    "loop_capped": "loop detector",
}


class SubagentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        return self in (
            SubagentStatus.COMPLETED,
            SubagentStatus.FAILED,
            SubagentStatus.CANCELLED,
            SubagentStatus.TIMED_OUT,
        )


@dataclass
class SubagentResult:
    """Результат-холдер одной делегации."""

    task_id: str
    status: SubagentStatus = SubagentStatus.PENDING
    result: str | None = None
    error: str | None = None
    stop_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    token_usage_records: list[dict[str, Any]] = field(default_factory=list)
    tool_receipts: list[dict[str, Any]] | None = field(default=None, kw_only=True)
    # Находки, зафиксированные Сабагентом (report_finding); ставит исполнитель
    # до терминала, вне first-writer-wins контракта — как и usage-записи
    findings: list[dict[str, Any]] = field(default_factory=list)

    def try_set_terminal(
        self,
        status: SubagentStatus,
        *,
        result: str | None = None,
        error: str | None = None,
        stop_reason: str | None = None,
        tool_receipts: list[dict[str, Any]] | None = None,
        token_usage_records: list[dict[str, Any]] | None = None,
    ) -> bool:
        if not status.is_terminal:
            raise ValueError(f"Status {status} is not terminal")
        if self.status.is_terminal:
            return False
        if result is not None:
            self.result = result
        if error is not None:
            self.error = error
        if stop_reason is not None:
            self.stop_reason = stop_reason
        if tool_receipts is not None:
            self.tool_receipts = [dict(r) for r in tool_receipts]
        if token_usage_records is not None:
            self.token_usage_records = list(token_usage_records)
        self.completed_at = datetime.now(UTC)
        self.status = status
        return True

    def update_token_usage_records(self, records: list[dict[str, Any]]) -> None:
        if not self.status.is_terminal:
            self.token_usage_records = list(records)

    def update_tool_receipts(self, receipts: list[dict[str, Any]] | None) -> None:
        if receipts is None:
            return
        if not self.status.is_terminal:
            self.tool_receipts = [dict(r) for r in receipts]


class StructuredSubagentResult(TypedDict):
    status: SubagentStatusValue
    stop_reason: NotRequired[str]
    error: NotRequired[str]
    result_brief: NotRequired[str]
    result_sha256: NotRequired[str]
    model_name: NotRequired[str]
    token_usage: NotRequired[dict[str, int]]
    tool_receipts: NotRequired[list[dict[str, Any]]]
    receipt_verdict: NotRequired[dict[str, Any]]


def _truncate_head_tail(text: str, max_chars: int = SUBAGENT_METADATA_TEXT_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars * 2 // 3
    tail = max_chars - head - 5
    return f"{text[:head]}\n...\n{text[-tail:]}"


def normalize_token_usage(value: Any) -> dict[str, int] | None:
    """Единый валидатор usage: все три ключа — неотрицательные int (bool — нет)."""
    if not isinstance(value, dict):
        return None
    out: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            return None
        out[key] = item
    return out


def make_subagent_additional_kwargs(
    status: SubagentStatus,
    *,
    result: str | None = None,
    error: str | None = None,
    stop_reason: str | None = None,
    model_name: str | None = None,
    token_usage: dict[str, Any] | None = None,
    tool_receipts: list[dict[str, Any]] | None = None,
    receipt_verdict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Структурные метаданные для ToolMessage.additional_kwargs (producer-строгий)."""
    if status.value not in SUBAGENT_STATUS_VALUES:
        raise ValueError(f"Non-terminal or unknown status for the wire: {status}")
    if stop_reason is not None and stop_reason not in SUBAGENT_STOP_REASON_VALUES:
        raise ValueError(f"Unknown stop_reason: {stop_reason!r}")
    kwargs: dict[str, Any] = {SUBAGENT_STATUS_KEY: status.value}
    if stop_reason is not None:
        kwargs[SUBAGENT_STOP_REASON_KEY] = stop_reason
    if error and status is not SubagentStatus.COMPLETED:
        kwargs[SUBAGENT_ERROR_KEY] = _truncate_head_tail(error)
    if status is SubagentStatus.COMPLETED and result:
        kwargs[SUBAGENT_RESULT_BRIEF_KEY] = _truncate_head_tail(result)
        kwargs[SUBAGENT_RESULT_SHA256_KEY] = hashlib.sha256(result.encode()).hexdigest()
    if model_name:
        kwargs[SUBAGENT_MODEL_NAME_KEY] = model_name
    usage = normalize_token_usage(token_usage)
    if usage is not None:
        kwargs[SUBAGENT_TOKEN_USAGE_KEY] = usage
    if tool_receipts is not None:
        kwargs[SUBAGENT_TOOL_RECEIPTS_KEY] = [dict(r) for r in tool_receipts]
    if receipt_verdict is not None:
        kwargs[SUBAGENT_RECEIPT_VERDICT_KEY] = dict(receipt_verdict)
    return kwargs


def format_subagent_result_message(
    status: SubagentStatus,
    *,
    result: str | None = None,
    error: str | None = None,
    stop_reason: str | None = None,
) -> str:
    """Модель-видимый текст ToolMessage."""
    cap = f" (capped: {_STOP_REASON_LABELS[stop_reason]})" if stop_reason else ""
    match status:
        case SubagentStatus.COMPLETED:
            return f"Task Succeeded{cap}. Result:\n{result or 'No response generated'}"
        case SubagentStatus.TIMED_OUT:
            return f"Task Timed Out{cap}. {error or ''}".rstrip()
        case SubagentStatus.CANCELLED:
            return f"Task Cancelled{cap}. {error or ''}".rstrip()
        case _:
            return f"Task Failed{cap}. {error or 'Unknown error'}"


def read_subagent_result_metadata(
    additional_kwargs: dict[str, Any] | None,
) -> StructuredSubagentResult | None:
    """Читатель ничего не доверяет: невалидные поля молча отбрасываются."""
    if not isinstance(additional_kwargs, dict):
        return None
    status = additional_kwargs.get(SUBAGENT_STATUS_KEY)
    if status not in SUBAGENT_STATUS_VALUES:
        return None
    out: StructuredSubagentResult = {"status": status}
    stop_reason = additional_kwargs.get(SUBAGENT_STOP_REASON_KEY)
    if stop_reason in SUBAGENT_STOP_REASON_VALUES:
        out["stop_reason"] = stop_reason
    error = additional_kwargs.get(SUBAGENT_ERROR_KEY)
    if isinstance(error, str) and error:
        out["error"] = _truncate_head_tail(error)
    brief = additional_kwargs.get(SUBAGENT_RESULT_BRIEF_KEY)
    if isinstance(brief, str) and brief:
        out["result_brief"] = _truncate_head_tail(brief)
    sha = additional_kwargs.get(SUBAGENT_RESULT_SHA256_KEY)
    if isinstance(sha, str) and _SHA256_HEX_RE.fullmatch(sha):
        out["result_sha256"] = sha
    model_name = additional_kwargs.get(SUBAGENT_MODEL_NAME_KEY)
    if isinstance(model_name, str) and model_name:
        out["model_name"] = model_name
    usage = normalize_token_usage(additional_kwargs.get(SUBAGENT_TOKEN_USAGE_KEY))
    if usage is not None:
        out["token_usage"] = usage
    receipts = additional_kwargs.get(SUBAGENT_TOOL_RECEIPTS_KEY)
    if isinstance(receipts, list):
        out["tool_receipts"] = [r for r in receipts if isinstance(r, dict)]
    verdict = additional_kwargs.get(SUBAGENT_RECEIPT_VERDICT_KEY)
    if isinstance(verdict, dict):
        out["receipt_verdict"] = verdict
    return out
