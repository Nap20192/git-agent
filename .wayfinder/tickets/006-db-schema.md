# Схема БД v1 + миграции

Type: wayfinder:grilling
Status: closed
Assignee: vnkjd
Blocked by: [Модель вебхуков](002-webhooks-model.md), [Пользователи и OAuth-связки](003-users-oauth.md), [Сборки Агентов и реестр раннеров](004-agent-registry.md)

## Question

Итоговая схема всех сущностей, границы владения в Postgres, инструмент миграций.

## Answer

- **Одна база** `git_agent` (порт 5433); таблицы backend'а — в Postgres-схеме **`hub.*`**, агентские остаются в `public`.
- **Мигратор** — нумерованные SQL в `migrations/backend/` + мини-раннер на Go (`backend/cmd/migrate`, таблица `hub.schema_migrations`), зеркало питоновского. `task backend:migrate`.
- **Схема** — [migrations/backend/001_init.sql](../../migrations/backend/001_init.sql), диаграмма — [migrations/backend/ERD.md](../../migrations/backend/ERD.md). 15 таблиц: users/sessions/identities; llm_connections/sandbox_connections/agent_builds; repositories/events/outbox; sandbox_instances/agent_instances/instance_events/runners; reports/findings.
- **Ключевые инварианты в DDL**: identities unique (provider, provider_user_id); repositories unique (user_id, provider, external_id); events unique (provider, delivery_id); agent_instances unique (build_id, repository_id) + CHECK «running ⇒ есть runner_id»; instance_events PK (instance_id, dedup_key); partial-индекс на неопубликованный outbox.
- **Песочница ↔ агенты = 1:N**: у Экземпляра одна песочница (FK), песочницу могут делить несколько Экземпляров.
- Применено к локальной БД и проверено на идемпотентность (повторный прогон — no-op, 16 таблиц в hub).
