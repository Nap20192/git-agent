# no-default-build

## Why

«Дефолтная Сборка» неявно обслуживала любой репозиторий без подписок: первая созданная Сборка автоматически становилась дефолтной, ping после подключения репо плодил её Экземпляр, а пользователь не понимал, какой агент и почему работает на репо. Пользователь хочет назначать агентов сам.

## What Changes

- Понятие дефолтной Сборки удалено: колонка `hub.agent_builds.is_default` (миграция 008), поле `isDefault` в API/фронте, запрос `DefaultBuild`, автоназначение первой Сборки дефолтной.
- `MatchedBuilds` (вебхук, trigger, raise) — строго по подпискам. Репозиторий без подписок: События только в журнал, Экземпляры не создаются, в RabbitMQ ничего не уходит.
- Фронт: без «make default» и карточки default build; репо без подписки честно показывает «no subscription — nothing will run» и просит подписать Сборку на странице репо; в форме подключения репо опция «none — subscribe later on the repo page».

## Capabilities

### Modified Capabilities

- hub (спека вне openspec — `.wayfinder`, тикет 011): маршрутизация Событий по Сборкам — только подписки.

## Impact

- `backend/`: домен/порты/стор/httpapi/openapi, тесты (webhook fallback → journal-only, trigger, app repository).
- `migrations/backend/008_drop_default_build.sql`, `docs/ERD.md`.
- `frontend/`: contract, mock, Dash/Repositories/Builds/Repo/Playground.
