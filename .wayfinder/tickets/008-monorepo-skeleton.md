# Размещение Go-сервиса в монорепе

Type: wayfinder:grilling
Status: closed
Assignee: vnkjd
Blocked by: —

## Question

Имя директории (hub/? server-go/?), путь Go-модуля, layout (cmd/internal), интеграция в Taskfile (task hub:run и т.п.), где живут его миграции относительно существующих migrations/ Python-части.

## Answer

Верхний уровень: `frontend/`, `backend/`, `agent/`, `deploy/`, `migrations/`.
- Python целиком переехал в `agent/` (импорты не изменились — корень Python-проекта теперь `agent/`); перенос выполнен сразу, одним заходом.
- Миграции — общая папка наверху с подпапками per-service: `migrations/agent/` (существующие SQL + migrate.py; симлинк `agent/migrations` сохраняет `python -m migrations.migrate` и импорт в conftest), `migrations/backend/` появится с первой Go-миграцией.
- Go: модуль `github.com/vnkjd/git-agent/backend`, layout `cmd/hub` + `internal/`, конфиг через env. Скелет создан, `task backend:build|run` в Taskfile.
- Python-таски Taskfile получили `dir: agent`, имена не менялись; `task app` чинён под новые пути.
- Проверено: `task backend:build`, `task lint`, unit-тесты (181 passed), `task migrate` через симлинк.
