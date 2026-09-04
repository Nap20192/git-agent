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


def test_production_preset_summarizes_at_500k():
    """Продакшен-пресет — prod_v3: суммаризация с 500k токенов (решение 2026-09-04),
    остальное как у prod_v2 (structured_prefix, keep 50k, без context editing)."""
    preset = resolve_memory_preset()
    assert preset.name == "prod_v3"
    assert preset.summarization_trigger_tokens == 500_000
    assert preset.summarization_keep_tokens == 50_000
    assert preset.summarization_strategy == "structured_prefix"
    assert preset.context_editing is False
