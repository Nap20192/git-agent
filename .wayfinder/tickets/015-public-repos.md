# Публичные чужие репозитории (watch-only, без вебхука)

Type: wayfinder:grilling
Status: closed
Assignee: vnkjd
Blocked by: —

## Question

Проверять чужие публичные репозитории, на которые нельзя повесить вебхук (нет admin-прав).

## Answer

- Новый режим подключения **watch**: репозиторий добавляется **по URL** (`https://github.com/owner/repo`), hub проверяет через публичный API, что он существует и публичный, и создаёт запись **без хука** (`webhook_provider_id = NULL`, поле `mode: hook|watch`).
- **Только ручной запуск** — «Run agent» / «Full scan» (HEAD публичным API, клон по https без токена). Поллера нет (осознанно: пользователь выбрал ручной режим); в туман — поллер как замена вебхука.
- UI: в drawer «connect» — вкладка/поле «public repo by URL»; в списке и на странице репо — бейдж `watch` вместо «webhook installed»; disconnect не ходит к провайдеру за хуком.
- Раннер не меняется.
