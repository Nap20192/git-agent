"""Тесты фабрики трейсинг-коллбэков (референс-семантика deerflow/tracing)."""

import pytest

from core.tracing import (
    build_langfuse_trace_metadata,
    build_tracing_callbacks,
    get_enabled_tracing_providers,
    inject_langfuse_metadata,
    reset_tracing_config,
)
from core.tracing import factory as tracing_factory

_ALL_VARS = [
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_TRACING",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGCHAIN_PROJECT",
    "LANGSMITH_ENDPOINT",
    "LANGCHAIN_ENDPOINT",
    "LANGFUSE_TRACING",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_HOST",
]


@pytest.fixture(autouse=True)
def clean_tracing_env(monkeypatch):
    for var in _ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    reset_tracing_config()
    yield
    reset_tracing_config()


def test_disabled_means_empty():
    assert get_enabled_tracing_providers() == []
    assert build_tracing_callbacks() == []


def test_keys_without_flag_do_not_enable(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "k")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    assert build_tracing_callbacks() == []


def test_enabled_but_unconfigured_fails_fast(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        build_tracing_callbacks()


def test_langfuse_missing_keys_named(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    with pytest.raises(ValueError, match="LANGFUSE_SECRET_KEY"):
        build_tracing_callbacks()


def test_langsmith_tracer_created_with_project(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "1")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "my-project")
    callbacks = build_tracing_callbacks()
    assert len(callbacks) == 1
    assert type(callbacks[0]).__name__ == "LangChainTracer"
    assert callbacks[0].project_name == "my-project"


def test_langfuse_host_wins_over_base_url_alias(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_HOST", "https://canonical.example")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://stale.example")
    from core.tracing import get_tracing_config

    assert get_tracing_config().langfuse.host == "https://canonical.example"


def test_legacy_langchain_aliases(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "legacy-key")
    assert get_enabled_tracing_providers() == ["langsmith"]


def test_both_providers_are_additive(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "k")
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    callbacks = build_tracing_callbacks()
    names = [type(c).__name__ for c in callbacks]
    assert names[0] == "LangChainTracer"
    assert "CallbackHandler" in names[1]


def test_provider_error_is_wrapped_with_name(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "k")

    def boom(config):
        raise ImportError("No module named 'x'")

    monkeypatch.setattr(tracing_factory, "_create_langsmith_tracer", boom)
    with pytest.raises(RuntimeError, match="LangSmith tracing initialization failed"):
        build_tracing_callbacks()


def test_langfuse_metadata_lifecycle(monkeypatch):
    assert build_langfuse_trace_metadata(thread_id="42") == {}
    config: dict = {"metadata": {"x": 1}}
    inject_langfuse_metadata(config, thread_id="42")
    assert config["metadata"] == {"x": 1}

    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    reset_tracing_config()

    metadata = build_langfuse_trace_metadata(
        thread_id="42", model_name="deepseek-chat", environment="prod"
    )
    assert metadata["langfuse_session_id"] == "42"
    assert metadata["langfuse_trace_name"] == "repo-scan"
    assert metadata["langfuse_tags"] == ["env:prod", "model:deepseek-chat"]

    config = {"metadata": {"langfuse_session_id": "upstream"}}
    inject_langfuse_metadata(config, thread_id="42", model_name="m")
    assert config["metadata"]["langfuse_session_id"] == "upstream"
    assert config["metadata"]["langfuse_tags"] == ["model:m"]

    # сквозной trace_id хода — тег и поле
    config = {}
    inject_langfuse_metadata(config, thread_id="42", trace_id="c" * 32)
    assert config["metadata"]["langfuse_tags"] == ["trace:" + "c" * 32]
    assert config["metadata"]["trace_id"] == "c" * 32
