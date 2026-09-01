"""Фабрика LLM: OpenAI-совместимый endpoint (api_base/key/model — на каждый Ран)."""

from langchain.chat_models import init_chat_model
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel

from core.config import settings


def make_model(
    *,
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> BaseChatModel:
    model_name = model or settings.llm_model
    if not model_name:
        raise ValueError("LLM model is not set: pass --model or LLM_MODEL in .env")
    return init_chat_model(
        model_name,
        model_provider="openai",
        base_url=api_base or settings.llm_api_base or None,
        api_key=api_key or settings.llm_api_key or "not-set",
    )


def langfuse_callbacks() -> list[BaseCallbackHandler]:
    """Langfuse-хендлер, если ключи заданы; иначе пусто (трейсинг опционален)."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return []
    from langfuse.langchain import CallbackHandler

    return [CallbackHandler()]
