-- Сохранённые LLM-подключения для HTTP-gateway (frontend/docs/openapi.yaml).
-- api_key хранится как есть (как runs.llm_api_key); наружу — только маска.
CREATE TABLE connections (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    api_base TEXT NOT NULL,
    api_key TEXT NOT NULL,
    model TEXT NOT NULL,
    last_check JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
