"""Параметры LLM-подключения → kwargs модели (core/agents/llm.py)."""

from core.agents.llm import make_model, model_kwargs


def test_params_map_to_chat_openai_kwargs():
    kw = model_kwargs(
        {
            "temperature": 0.2,
            "topP": 0.9,
            "maxTokens": 16384,
            "contextWindow": 262144,  # не параметр запроса
            "reasoningEffort": "high",
            "timeoutSeconds": 600,
            "maxRetries": 3,
            "extra": {"top_k": 20, "min_p": 0.05},
        }
    )
    assert kw == {
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 16384,
        "reasoning_effort": "high",
        "timeout": 600,
        "max_retries": 3,
        "extra_body": {"top_k": 20, "min_p": 0.05},
    }


def test_empty_and_none_params_send_nothing():
    assert model_kwargs(None) == {}
    assert model_kwargs({}) == {}
    assert model_kwargs({"reasoningEffort": "none", "extra": {}, "temperature": None}) == {}


def test_make_model_applies_params():
    m = make_model(
        model="qwen",
        api_base="http://localhost:8080",
        api_key="k",
        params={"maxTokens": 16384, "temperature": 0.1, "extra": {"top_k": 20}},
    )
    assert m.max_tokens == 16384 and m.temperature == 0.1
    assert m.extra_body == {"top_k": 20}
