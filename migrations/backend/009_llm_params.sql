-- Параметры модели у LLM-подключения: temperature, topP, maxTokens, contextWindow,
-- reasoningEffort, timeoutSeconds, maxRetries, extra{…} — раннер отдаёт их в модель.
ALTER TABLE hub.llm_connections ADD COLUMN IF NOT EXISTS params JSONB NOT NULL DEFAULT '{}'::jsonb;
