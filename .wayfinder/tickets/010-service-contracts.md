# Контракты между сервисами

Type: wayfinder:grilling
Status: closed
Assignee: vnkjd
Blocked by: —

## Question

JSON-схема События в Rabbit и кто резолвит Экземпляр; HTTP API раннера в обе стороны; контракт записи результатов и чат-поток.

## Answer

- **Экземпляр резолвит backend на вебхуке** (upsert: repo → Сборка → Экземпляр) — в Событии едут готовые id. Схема сообщения (camelCase JSON):
  `{eventId, instanceId, threadId, repositoryId, provider, action, commitSha?, ref?, dedupKey}`.
  Раннер тупой: клеймит Экземпляр (CAS down→running в БД) и исполняет.
- **Событие для уже поднятого Экземпляра**: раннер-получатель форвардит его держателю напрямую — `POST http://<адрес держателя>/instances/{id}/events` (адрес из `hub.runners`). Держатель мёртв ⇒ общий механизм heartbeat-таймаута вернёт Событие в outbox.
- **API раннера (v1)**: `POST /instances/{id}/raise`, `POST /instances/{id}/events`, `POST /instances/{id}/chat` (SSE-стрим), `POST /instances/{id}/stop`, `GET /health`. Обратная сторона: `POST {backend}/api/runners` при старте, `POST /api/runners/{id}/heartbeat` каждые N секунд.
- **Результаты**: агентские тулзы `report_finding` → `hub.findings` (severity, cwe?, cve?, file, lines, evidence, remediation) и `write_report` → `hub.reports` (summary, event_id). Чат до фронта — SSE через backend (прокси раннера), события типа `chat` как в текущем гейтвее.
- **Форматы**: везде camelCase JSON; контракт backend — OpenAPI (`backend/docs/openapi.yaml`), по образцу фронтового.
