"""Фабрика LangChain-коллбэков трейсинга (референс: deerflow/tracing/factory.py).

Коллбэки создаются на КАЖДЫЙ запуск (не кэшируются): дёшево — конфиг в кэше,
Langfuse-клиент — синглтон — и никакого разделяемого состояния хендлеров
между конкурентными ранами. Провайдеры аддитивны.
"""

from __future__ import annotations

from typing import Any

from core.tracing.config import (
    get_enabled_tracing_providers,
    get_tracing_config,
    validate_enabled_tracing_providers,
)


def _create_langsmith_tracer(config: Any) -> Any:
    # Ленивый импорт: процесс без LangSmith не платит за него и не падает
    # без пакета. API-ключ/endpoint трейсер сам берёт из окружения.
    from langchain_core.tracers.langchain import LangChainTracer

    return LangChainTracer(project_name=config.project)


def _create_langfuse_handler(config: Any) -> Any:
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

    # langfuse>=4: креды регистрируются через клиент-синглтон; конструктор без
    # сохранения результата НАМЕРЕННО — он кладёт клиента в глобальный реестр
    # по public_key, а CallbackHandler(public_key=...) к нему привязывается.
    Langfuse(
        secret_key=config.secret_key,
        public_key=config.public_key,
        host=config.host,
    )
    return LangfuseCallbackHandler(public_key=config.public_key)


def build_tracing_callbacks() -> list[Any]:
    """Коллбэки для всех включённых и полностью настроенных провайдеров.

    Fail-fast: провайдер включён флагом, но креды не полны → ValueError
    (тихая потеря трейсов хуже пятисотки). Ошибка создания заворачивается
    в RuntimeError с именем провайдера, исходный стектрейс сохраняется.
    """
    validate_enabled_tracing_providers()
    enabled_providers = get_enabled_tracing_providers()
    if not enabled_providers:
        return []

    tracing_config = get_tracing_config()
    callbacks: list[Any] = []
    for provider in enabled_providers:
        if provider == "langsmith":
            try:
                callbacks.append(_create_langsmith_tracer(tracing_config.langsmith))
            except Exception as exc:
                raise RuntimeError(f"LangSmith tracing initialization failed: {exc}") from exc
        elif provider == "langfuse":
            try:
                callbacks.append(_create_langfuse_handler(tracing_config.langfuse))
            except Exception as exc:
                raise RuntimeError(f"Langfuse tracing initialization failed: {exc}") from exc
    return callbacks
