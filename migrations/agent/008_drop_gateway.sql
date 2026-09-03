-- Durable-gateway (Раны) удалён: агент живёт только как Раннер под hub.
-- Схема hub.* и чекпоинты LangGraph не затрагиваются.
DROP TABLE IF EXISTS sandbox_instances;
DROP TABLE IF EXISTS run_events;
DROP TABLE IF EXISTS connections;
DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS sandboxes;
DROP TABLE IF EXISTS repositories;
