## 1. Рантайм: чат поверх треда

- [x] 1.1 `Runtime.chat(run_id, message)` — пересборка лид-графа с checkpointer +
  `thread_id=str(run_id)`, `provision_sandbox(is_resume=True)`, `astream` с
  `{messages:[HumanMessage]}`, стрим `(mode, data)`; в конце `sandbox.close()` (release)
- [x] 1.2 Персист ходов: `store.add_event(run_id, "chat", {role,text})` для user и agent
- [x] 1.3 Per-run `asyncio.Lock` — сериализация параллельных сообщений
- [x] 1.4 Отказ, если у Рана нет чекпоинта/не agent (проверяется на gateway по режиму)

## 2. Gateway

- [x] 2.1 `GET /api/runs/{id}/chat` — история (chat-события → `[{role,text,at}]`)
- [x] 2.2 `POST /api/runs/{id}/chat` — `StreamingResponse` (text/event-stream) ходов;
  422 для не-agent Рана
- [x] 2.3 `infra/server/wire.py` — сериализация chat-хода и элемента истории

## 3. Фронтенд

- [x] 3.1 API: `chatHistory(runId)`, `sendChat(runId, message, {onEvent, onDone})`
  (fetch-reader стрима); типы `ChatTurn`
- [x] 3.2 Панель чата на RunDetailScreen (agent + терминальный): транскрипт + инпут,
  live-рендер ответа (tool-calls свёрнуты), append по завершении
- [x] 3.3 `docs/openapi.yaml` — оба маршрута + схемы

## 4. Тесты

- [x] 4.1 `tests/unit`: `Runtime.chat` над memory-рантаймом (фейк-граф) — стрим +
  персист chat-событий + неизменность статуса Рана
- [x] 4.2 gateway: POST чат стримит, GET отдаёт историю; 422 для pipeline
- [x] 4.3 `task check` зелёный

## 5. Документация

- [x] 5.1 CLAUDE.md — секция про пост-ран-чат (тред-континуация, chat-события, agent-only)
