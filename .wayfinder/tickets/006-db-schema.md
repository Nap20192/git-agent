# Схема БД v1 + миграции

Type: wayfinder:grilling
Status: open
Assignee:
Blocked by: [Модель вебхуков](002-webhooks-model.md), [Пользователи и OAuth-связки](003-users-oauth.md), [Сборки Агентов и реестр раннеров](004-agent-registry.md)

## Question

Итоговая схема: users, oauth-связки, repositories (+привязка к Сборке, per-repo webhook-секрет), журнал событий (unique provider+delivery_id) + outbox, сборки агентов, экземпляры агентов (долгоживущие: один на сборка+repo, статус down/running с single-running инвариантом, журнал обработанных Событий с dedup_key), раннеры (адрес, слоты, heartbeat), llm/sandbox connections, sandbox_instances — поля, связи, уникальности (Экземпляр: сборка+repo+commit). Одна общая Postgres — подтвердить и решить границы схем (`hub.*`/`agent.*`?) и судьбу текущих таблиц агента. Инструмент миграций на Go (goose / golang-migrate / нумерованные SQL как в Python-части). Это финальный тикет карты — его Answer и есть «сделаем базу данных».
