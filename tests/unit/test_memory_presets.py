"""Тесты резолва Пресетов памяти: приоритет источников и ошибки без фолбэка."""

import pytest

from core.memory import (
    PRODUCTION_FALLBACK_MEMORY_PRESET,
    PRODUCTION_MEMORY_PRESET,
    resolve_memory_preset,
)


def test_priority_explicit_over_env_over_default(monkeypatch):
    monkeypatch.setenv("GIT_AGENT_MEMORY_PRESET", "aggressive")
    assert resolve_memory_preset("full_history").name == "full_history"
    assert resolve_memory_preset().name == "aggressive"
    monkeypatch.delenv("GIT_AGENT_MEMORY_PRESET")
    assert resolve_memory_preset().name == PRODUCTION_MEMORY_PRESET


def test_default_depends_on_model_provider():
    assert resolve_memory_preset(model_name="deepseek-chat").name == PRODUCTION_MEMORY_PRESET
    assert resolve_memory_preset(model_name="claude-x").name == PRODUCTION_FALLBACK_MEMORY_PRESET


def test_unknown_name_raises_not_falls_back(monkeypatch):
    with pytest.raises(ValueError, match="Unknown memory preset"):
        resolve_memory_preset("martian")
    monkeypatch.setenv("GIT_AGENT_MEMORY_PRESET", "martian")
    with pytest.raises(ValueError, match="Unknown memory preset"):
        resolve_memory_preset()


def test_incompatible_provider_raises():
    from core.memory import PRESET_PROVIDER_ALLOWLIST

    name = next(iter(PRESET_PROVIDER_ALLOWLIST))
    allowed = PRESET_PROVIDER_ALLOWLIST[name]
    incompatible = "claude-x" if "anthropic" not in allowed else "gpt-x"
    with pytest.raises(ValueError, match="does not support provider"):
        resolve_memory_preset(name, model_name=incompatible)
