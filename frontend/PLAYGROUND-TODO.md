# Playground — что нужно от hub

Экран `/instances/:id` (PlaygroundScreen) сейчас живёт на polling'е существующих
эндпоинтов. Чего не хватает в `backend/docs/openapi.yaml`, чтобы сделать его
по-настоящему живым:

1. ~~**SSE активности прогона.**~~ ✅ Сделано (тикет 012):
   `GET /api/instances/{id}/activity?eventId=` — кадры `ActivityEvent`
   (openapi.yaml), живой ход стримится, завершённый реплеится из `hub.activity`.
   Кормит граф Рана «Лид → Сабагенты» и activity-лог Playground.

2. **Журнал обработки Событий Экземпляром.** Статус per (instanceId, eventId):
   `queued | processing | done | failed` + timestamps. Сейчас Playground выводит
   «processed» из наличия Отчёта с `eventId`, а «processing/queued» различить
   нечем.

3. **История чата.** `GET /api/instances/{id}/chat` (transcript) — сейчас
   переписка session-local и теряется при перезагрузке страницы.

4. **Занятость слотов раннера.** `Runner` отдаёт только `slots` (ёмкость);
   busy-счётчик фронт выводит сам из running-Экземпляров с этим `runnerId` —
   неточно, если раннер обслуживает чужих пользователей. Нужно поле
   `busySlots` (или аналог) в `GET /api/runners`.

5. **Контракт trigger в openapi.yaml.** Фронт уже дёргает
   `POST /api/repositories/{id}/trigger` (тело `{ref?, commitSha?}`, 202 →
   `{event, instances}` — см. `TriggerResult` в contract.ts). Форма ответа
   согласована устно — сверить с openapi.yaml, когда бэкенд-коммит приедет.

6. **Стрим статуса Экземпляра.** Вместо 5s-поллинга `GET /api/instances/{id}` —
   SSE/WebSocket с переходами down↔running (+runnerId, sandboxInstanceId).
