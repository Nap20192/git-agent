"""Langfuse trace-attribute метаданные (референс: deerflow/tracing/metadata.py)."""

from __future__ import annotations

from typing import Any

from core.tracing.config import get_enabled_tracing_providers

_DEFAULT_TRACE_NAME = "repo-scan"


def build_langfuse_trace_metadata(
    *,
    thread_id: str | None,
    trace_name: str | None = None,
    model_name: str | None = None,
    environment: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Метаданные для config["metadata"]; {} если Langfuse выключен.
    trace_id — сквозной id хода (pkg/trace): тег `trace:<id>` + поле trace_id."""
    if "langfuse" not in get_enabled_tracing_providers():
        return {}

    metadata: dict[str, Any] = {
        "langfuse_session_id": thread_id,
        "langfuse_trace_name": trace_name or _DEFAULT_TRACE_NAME,
    }
    tags = []
    if environment:
        tags.append(f"env:{environment}")
    if model_name:
        tags.append(f"model:{model_name}")
    if trace_id:
        tags.append(f"trace:{trace_id}")
        metadata["trace_id"] = trace_id
    if tags:
        metadata["langfuse_tags"] = tags
    return metadata


def inject_langfuse_metadata(
    config: dict,
    *,
    thread_id: str | None,
    trace_name: str | None = None,
    model_name: str | None = None,
    environment: str | None = None,
    trace_id: str | None = None,
) -> None:
    """Вмержить метаданные в config["metadata"] (in place)."""
    langfuse_metadata = build_langfuse_trace_metadata(
        thread_id=thread_id,
        trace_name=trace_name,
        model_name=model_name,
        environment=environment,
        trace_id=trace_id,
    )
    if not langfuse_metadata:
        return
    merged = dict(config.get("metadata") or {})
    for key, value in langfuse_metadata.items():
        merged.setdefault(key, value)
    config["metadata"] = merged
