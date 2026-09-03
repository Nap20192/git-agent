# HTTP-поверхность backend v1

Type: wayfinder:grilling
Status: closed
Assignee: vnkjd
Blocked by: [Схема БД v1 + миграции](006-db-schema.md)

## Question

Роуты v1 поверх решённой модели; формат; контракт для фронта.

## Answer

Полный контракт — **[backend/docs/openapi.yaml](../../backend/docs/openapi.yaml)** (camelCase, по образцу фронтового). Состав:

- **Auth**: `/api/auth/{provider}/login|callback` (вход и добавление связок одним флоу), `/api/auth/logout`, `/api/me`; связки `/api/identities` (+`/{id}/repos` — прокси списка репо провайдера).
- **Репозитории**: CRUD подключения (`POST` создаёт webhook, `DELETE` снимает), `PATCH {buildId}`, журнал `/{id}/events`.
- **Вебхуки**: `POST /hooks/{provider}/{repositoryId}` — id в URL ради секрета до проверки подписи; всегда 200.
- **Сборки** `/api/builds` CRUD; **подключения** `/api/connections/llm|sandbox` (ключи наружу только маской).
- **Экземпляры**: список/деталь, `POST /{id}/chat` (SSE, поднимает down через раннер), `/{id}/stop`, `/{id}/reports`, `/{id}/findings`.
- **Раннеры**: `POST /api/runners` (регистрация), `/{id}/heartbeat`; auth раннерных роутов — общий секрет `RUNNER_TOKEN` в заголовке `X-Runner-Token` (v1).
