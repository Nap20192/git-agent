"""Memory/context-management presets."""

from __future__ import annotations

import os

from core.memory.config import MemoryConfig
from core.memory.presets import (
    DEFAULT_MEMORY_PRESET,
    MEMORY_PRESETS,
    PRESET_PROVIDER_ALLOWLIST,
    PRODUCTION_FALLBACK_MEMORY_PRESET,
    PRODUCTION_LONG_CONTEXT_PROVIDERS,
    PRODUCTION_MEMORY_PRESET,
)
from core.memory.prompts import (
    CONTEXT_RESET_SUMMARY_PROMPT,
    DELTA_SUMMARY_PROMPT,
    SELECTIVE_RETENTION_SUMMARY_PROMPT,
)

__all__ = [
    "CONTEXT_RESET_SUMMARY_PROMPT",
    "DEFAULT_MEMORY_PRESET",
    "DELTA_SUMMARY_PROMPT",
    "MEMORY_PRESETS",
    "PRESET_PROVIDER_ALLOWLIST",
    "PRODUCTION_FALLBACK_MEMORY_PRESET",
    "PRODUCTION_LONG_CONTEXT_PROVIDERS",
    "PRODUCTION_MEMORY_PRESET",
    "SELECTIVE_RETENTION_SUMMARY_PROMPT",
    "MemoryConfig",
    "memory_preset_supports_model",
    "production_memory_preset_name",
    "resolve_memory_preset",
]


def _model_provider(model_name: str) -> str:
    normalized = (model_name or "").strip()
    if ":" in normalized:
        return normalized.partition(":")[0]
    if normalized.startswith("gpt-"):
        return "openai"
    if normalized.startswith("claude"):
        return "anthropic"
    if normalized.startswith("gemini"):
        return "google-genai"
    if normalized.startswith("deepseek"):
        return "deepseek"
    return ""


def production_memory_preset_name(model_name: str = "") -> str:
    """Return the production preset compatible with ``model_name``."""
    provider = _model_provider(model_name)
    if not provider or provider in PRODUCTION_LONG_CONTEXT_PROVIDERS:
        return PRODUCTION_MEMORY_PRESET
    return PRODUCTION_FALLBACK_MEMORY_PRESET


def memory_preset_supports_model(preset_name: str, model_name: str) -> bool:
    """Whether a selected preset supports the requested provider."""
    allowed = PRESET_PROVIDER_ALLOWLIST.get(preset_name)
    if allowed is None or not model_name:
        return True
    return _model_provider(model_name) in allowed


def resolve_memory_preset(name: str | None = None, *, model_name: str = "") -> MemoryConfig:
    explicit = (name or "").strip()
    environment = os.environ.get("GIT_AGENT_MEMORY_PRESET", "").strip()
    requested = explicit or environment or production_memory_preset_name(model_name)
    config = MEMORY_PRESETS.get(requested)
    if config is None:
        known = ", ".join(sorted(MEMORY_PRESETS))
        raise ValueError(f"Unknown memory preset {requested!r}. Known presets: {known}")
    if not memory_preset_supports_model(requested, model_name):
        provider = _model_provider(model_name) or "unknown"
        allowed = ", ".join(sorted(PRESET_PROVIDER_ALLOWLIST[requested]))
        raise ValueError(
            f"Memory preset {requested!r} does not support provider {provider!r}; "
            f"supported providers: {allowed}"
        )
    return config
