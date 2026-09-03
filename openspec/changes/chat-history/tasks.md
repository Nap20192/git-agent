# chat-history — Tasks

## 1. Раннер
- [x] 1.1 `ActivityCollector`: `chat_user`/`chat_agent`, накопление текста AI-сообщений (`message_text` — строка либо content-блоки)
- [x] 1.2 `RunnerService.chat`: кадры реплик в журнал хода
- [x] 1.3 `chat_stream`: `stream_mode` += `messages`; `chat_events`: token / message / activity, без токенов Сабагентов
- [x] 1.4 Тесты: кадры чата, стрим токенов, транскрипт коллектора

## 2. Hub
- [x] 2.1 sqlc `Messages` (activity ⋈ events, курсор before, limit)
- [x] 2.2 `domain.ChatMessage`, порт, store, `GET /api/instances/{id}/messages`, openapi (`ChatMessage`, `ChatEvent.kind` += message)

## 3. Фронт
- [x] 3.1 `listMessages` в контракте/клиенте/mock
- [x] 3.2 `InstanceChatPanel`: история + «earlier», токены/message, stop, textarea, автоскролл, время
