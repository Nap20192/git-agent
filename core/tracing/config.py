"""Tracing-конфигурация (референс: deerflow/config/tracing_config.py).

Читает env один раз и кэширует (ленивый синглтон с double-checked locking).
Ключевое различие: explicitly_enabled (флаг стоит) vs enabled_providers (флаг
стоит И креды полные). Первое — для fail-fast валидации, второе — для
фактического создания коллбэков. Monocle из референса не портирован: это
process-global OTel-инструментор гейтвея, которого у нас нет.
"""

from __future__ import annotations

import os
import threading

from pydantic import BaseModel

import core.config  # noqa: F401  # load_dotenv: .env должен попасть в env до чтения

_config_lock = threading.Lock()
_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _env_flag(*names: str) -> bool:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip().lower() in _TRUTHY_VALUES
    return False


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


class LangSmithTracingConfig(BaseModel):
    enabled: bool
    api_key: str | None
    project: str
    endpoint: str

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key)

    def validate_enabled(self) -> None:
        if self.enabled and not self.api_key:
            raise ValueError(
                "LangSmith tracing is enabled but LANGSMITH_API_KEY"
                " (or LANGCHAIN_API_KEY) is not set."
            )


class LangfuseTracingConfig(BaseModel):
    enabled: bool
    public_key: str | None
    secret_key: str | None
    host: str

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.public_key) and bool(self.secret_key)

    def validate_enabled(self) -> None:
        if not self.enabled:
            return
        missing = [
            name
            for name, value in (
                ("LANGFUSE_PUBLIC_KEY", self.public_key),
                ("LANGFUSE_SECRET_KEY", self.secret_key),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"Langfuse tracing is enabled but required settings are missing:"
                f" {', '.join(missing)}"
            )


class TracingConfig(BaseModel):
    langsmith: LangSmithTracingConfig
    langfuse: LangfuseTracingConfig

    @property
    def explicitly_enabled_providers(self) -> list[str]:
        enabled = []
        if self.langsmith.enabled:
            enabled.append("langsmith")
        if self.langfuse.enabled:
            enabled.append("langfuse")
        return enabled

    @property
    def enabled_providers(self) -> list[str]:
        enabled = []
        if self.langsmith.is_configured:
            enabled.append("langsmith")
        if self.langfuse.is_configured:
            enabled.append("langfuse")
        return enabled

    def validate_enabled(self) -> None:
        self.langsmith.validate_enabled()
        self.langfuse.validate_enabled()


_tracing_config: TracingConfig | None = None


def get_tracing_config() -> TracingConfig:
    global _tracing_config
    if _tracing_config is not None:
        return _tracing_config
    with _config_lock:
        if _tracing_config is not None:
            return _tracing_config
        _tracing_config = TracingConfig(
            langsmith=LangSmithTracingConfig(
                enabled=_env_flag("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"),
                api_key=_first_env("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"),
                project=_first_env("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT") or "git-agent",
                endpoint=_first_env("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT")
                or "https://api.smith.langchain.com",
            ),
            langfuse=LangfuseTracingConfig(
                enabled=_env_flag("LANGFUSE_TRACING"),
                public_key=_first_env("LANGFUSE_PUBLIC_KEY"),
                secret_key=_first_env("LANGFUSE_SECRET_KEY"),
                # LANGFUSE_HOST — каноническая переменная проекта (.env.example);
                # LANGFUSE_BASE_URL — алиас для совместимости с deer-flow
                host=_first_env("LANGFUSE_HOST", "LANGFUSE_BASE_URL")
                or "https://cloud.langfuse.com",
            ),
        )
        return _tracing_config


def get_enabled_tracing_providers() -> list[str]:
    return get_tracing_config().enabled_providers


def validate_enabled_tracing_providers() -> None:
    get_tracing_config().validate_enabled()


def is_tracing_enabled() -> bool:
    return bool(get_tracing_config().enabled_providers)


def reset_tracing_config() -> None:
    """Сбросить кэш (публичное API для тестов — не лезть в приватный атрибут)."""
    global _tracing_config
    with _config_lock:
        _tracing_config = None
