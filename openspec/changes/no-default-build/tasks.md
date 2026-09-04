# no-default-build — Tasks

## 1. Hub
- [x] 1.1 Миграция 008: drop `is_default`; sqlc без `DefaultBuild`/`is_default`
- [x] 1.2 `MatchedBuilds` только по подпискам; `createBuild` без автодефолта; DTO без `isDefault`; openapi
- [x] 1.3 Тесты: webhook без подписок → журнал без Экземпляров/outbox; trigger без подписок → instanceIds пуст; app-тесты сеют подписку

## 2. Фронт
- [x] 2.1 Контракт/мок без `isDefault`
- [x] 2.2 Builds: без «make default» и чекбокса; Repositories: карточка builds вместо default build; Repo: served = есть подписка; Playground/Dash
