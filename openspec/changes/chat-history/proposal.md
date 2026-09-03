# chat-history

## Why

Чат с Экземпляром жил только в памяти вкладки: перезагрузка страницы — транскрипт исчез, хотя тред агента (чекпоинты LangGraph) помнит всё. Ответ приходил не по мере генерации, а целым сообщением; остановить ход из чата было нельзя. Ожидание пользователя — как в ChatGPT/Claude: история хранится на сервере и подгружается при открытии, ответ стримится токенами, есть «стоп», ввод многострочный.

## What Changes

- Раннер пишет реплики чата в журнал хода (`hub.activity`): кадры `chat_user {text}` в начале хода и `chat_agent {text}` (текст всех AI-сообщений хода) в конце. Ход чата стримит `messages` LangGraph: токены Лида → кадр `token`; целое AI-сообщение из `updates` → кадр `message` (канон, заменяет накопленные токены; фолбэк без стриминга). Токены Сабагентов (тег `subagent:*`) в чат не идут.
- Hub: `GET /api/instances/{id}/messages?before=&limit=` — транскрипт из `hub.activity`: реплики + карточки ходов по Событиям (`run_started`/`run_finished` с `event_id`, `run_failed`), новые последними, пагинация назад курсором `before`. Контракт `ChatMessage`, `ChatEvent.kind` += `message`.
- Фронт: панель чата грузит историю при открытии («↑ earlier messages»), стримит токены, кнопка «■ stop» (= `POST /instances/{id}/stop`), textarea (Enter — отправить, Shift+Enter — перенос), автоскролл только у нижнего края, время реплики по ховеру.
- Одна беседа на Экземпляр (его тред) — «новый чат» намеренно отсутствует: смысл Экземпляра в накопленной памяти о репозитории.

## Capabilities

### Modified Capabilities

- `runner`: требование «HTTP API раннера» — кадры чата (`token`/`message`/`activity`) и персист транскрипта в журнале хода.

## Impact

- `agent/core/runner/activity.py` (`chat_user`/`chat_agent`, `message_text`), `service.py`, `executor.py` (`stream_mode` += `messages` для чата), `infra/server/runner_api.py::chat_events`.
- `backend`: запрос `Messages` (sqlc), `domain.ChatMessage`, порт `InstanceStore.Messages`, `GET /api/instances/{id}/messages`, `openapi.yaml`.
- `frontend`: `InstanceChatPanel`, контракт/клиент/mock (`listMessages`), стили.
- Ограничение (не в этом change): обрыв SSE клиентом (закрыл вкладку) по-прежнему отменяет ход чата — hub отменяет запрос к раннеру; ответ, начатый до обрыва, в историю не попадёт.
