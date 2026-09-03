# HTTP-поверхность backend v1

Type: wayfinder:grilling
Status: open
Assignee:
Blocked by: [Схема БД v1 + миграции](006-db-schema.md)

## Question

Роуты v1 поверх решённой модели: OAuth-вход (redirect/callback), связки, список репо провайдера и «подключить Репозиторий», webhook-приёмник, Сборки CRUD, Экземпляры (список, статус, chat-прокси в раннер), раннеры (регистрация, heartbeat). Формат — camelCase JSON как у существующего гейтвея? OpenAPI-файл как контракт для фронта?
