"""Фабрика LLM: OpenAI-совместимый endpoint (api_base/key/model — на каждый Ран) плюс
параметры модели из LLM-подключения (hub.llm_connections.params, camelCase)."""

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from core.config import settings

# ключ params → kwarg ChatOpenAI; остальное известное — ниже, неизвестное игнорируется
_DIRECT = {
    "temperature": "temperature",
    "topP": "top_p",
    "maxTokens": "max_tokens",
    "timeoutSeconds": "timeout",
    "maxRetries": "max_retries",
}


def model_kwargs(params: dict[str, Any] | None) -> dict[str, Any]:
    """params подключения → kwargs init_chat_model. reasoningEffort «none»/пусто — не
    слать; extra{} → extra_body (провайдер-специфичное: top_k, min_p, repeat_penalty, seed).
    contextWindow — не параметр запроса (для управления контекстом), сюда не попадает."""
    if not params:
        return {}
    kw: dict[str, Any] = {}
    for key, name in _DIRECT.items():
        if (v := params.get(key)) is not None:
            kw[name] = int(v) if name in ("max_tokens", "max_retries") else v
    if (effort := params.get("reasoningEffort")) and effort != "none":
        kw["reasoning_effort"] = effort
    if isinstance(extra := params.get("extra"), dict) and extra:
        kw["extra_body"] = dict(extra)
    return kw


def make_model(
    *,
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    params: dict[str, Any] | None = None,
) -> BaseChatModel:
    model_name = model or settings.llm_model
    if not model_name:
        raise ValueError("LLM model is not set: pass --model or LLM_MODEL in .env")
    return init_chat_model(
        model_name,
        model_provider="openai",
        base_url=api_base or settings.llm_api_base or None,
        api_key=api_key or settings.llm_api_key or "not-set",
        **model_kwargs(params),
    )
