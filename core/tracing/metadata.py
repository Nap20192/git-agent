"""Langfuse trace-attribute метаданные (референс: deerflow/tracing/metadata.py).

Langfuse v4 CallbackHandler поднимает зарезервированные ключи из
RunnableConfig.metadata на корневой трейс: langfuse_session_id (у нас —
thread_id рана, т.е. run id), langfuse_trace_name, langfuse_tags.
user_id/trace_context из референса не портированы — система однопользовательская.
"""

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
) -> dict[str, Any]:
    """Метаданные для config["metadata"]; {} если Langfuse выключен —
    вызывающий мержит безусловно, не задевая LangSmith."""
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
) -> None:
    """Вмержить метаданные в config["metadata"] (in place).

    Значения вызывающего побеждают через setdefault; no-op при выключенном
    Langfuse. Единая точка для CLI и воркера рантайма — пути не расходятся.
    """
    langfuse_metadata = build_langfuse_trace_metadata(
        thread_id=thread_id,
        trace_name=trace_name,
        model_name=model_name,
        environment=environment,
    )
    if not langfuse_metadata:
        return
    merged = dict(config.get("metadata") or {})
    for key, value in langfuse_metadata.items():
        merged.setdefault(key, value)
    config["metadata"] = merged
