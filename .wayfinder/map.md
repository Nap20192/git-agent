# Карта: Go-сервис мониторинга git (hub)

label: wayfinder:map

## Destination

Спека Go-сервиса + схема БД в миграциях, готовые к имплементации. Сервис живёт в монорепе git-agent, владеет: пользователями с OAuth-связками GitHub/GitLab, приёмом webhooks, созданием Экземпляров Сэндбоксов (OpenSandbox), публикацией Тасков в RabbitMQ, реестром агентов. Агент (Python) в этом заходе НЕ трогаем — контракт Таска фиксируем документом.

## Notes

- Домен: расширение git-agent; глоссарий — CONTEXT.md в корне, новые термины писать туда же.
- Скиллы: grilling + domain-modeling для decision-тикетов; golang-project-layout / golang-popular-libraries при выборе структуры и библиотек.
- Имплементация после карты пойдёт через OpenSpec (propose→apply→archive) — карта заканчивается на спеке, не на коде.
- Трекер: локальный markdown. Тикеты — `.wayfinder/tickets/NNN-*.md`; клейм — поле `Assignee:`; блокировки — поле `Blocked by:`; закрытие — `Status: closed` + секция `## Answer`.

## Decisions so far

Решения чартинг-сессии (без отдельных тикетов):

- Результат усилия — спека + миграции БД, не рабочий код.
- Монорепа: Go-сервис — директория внутри git-agent.
- Go-сервис — слой НАД агентом (агент со временем станет консьюмером Rabbit), но агента сейчас не трогаем.
- Экземпляры Сэндбоксов создаёт и владеет ими Go-сервис; агенту в Таске едет external_id.
- Мониторинг — webhooks (не polling).
- ~~Пользователи локальные; OAuth не для логина~~ — пересмотрено тикетом 003 (вход как в Railway).
- Реестр агентов — в скоупе; профили агентов — вне.
- ~~Новый термин: **Таск**~~ — отменён (см. ниже).
- [Контракт Таска → модель Событий](tickets/001-task-contract.md) — Таск и backend-Ран отменены; по Rabbit летят тонкие **События** с вебхуков, в БД живут **Сборки Агентов** (repo→Сборка 1:1) и **Экземпляры Агентов** (идемпотентность по сборка+repo+commit); слоты у Python-раннера, гарантии — БД+чекпоинты (auto-ack), результат агент пишет в БД тулзой.
- [Research: OpenSandbox из Go](tickets/007-opensandbox-go.md) — официальный Go SDK есть (alibaba/OpenSandbox, sdks/sandbox/go); API — `/v1/sandboxes` + заголовок `OPEN-SANDBOX-API-KEY`, тонкий клиент возможен, но SDK предпочтительнее.
- [Размещение Go-сервиса в монорепе](tickets/008-monorepo-skeleton.md) — верхний уровень `frontend/ backend/ agent/ deploy/ migrations/`; Python переехал в `agent/`, миграции per-service в `migrations/*`, Go-модуль `github.com/vnkjd/git-agent/backend` (`cmd/hub`). Перенос выполнен и проверен.
- [Модель вебхуков](tickets/002-webhooks-model.md) — хук на ВСЕ действия, backend вешает его сам при «подключении» Репозитория; per-repo секрет; всегда 200 наружу; дедуп по (provider, delivery_id) + `dedup_key` Экземпляра (commit_sha или event_id); **transactional outbox** → Rabbit; dev через cloudflared-туннель.
- [Пользователи и OAuth-связки](tickets/003-users-oauth.md) — вход кнопкой GitHub/GitLab (Railway-модель, паролей нет), session cookie; OAuth App у обоих; токены/секреты шифруются (AES-GCM, ключ в env); связок много (unique provider+provider_user_id), Репозиторий ссылается на свою связку.
- [Сборки Агентов и реестр раннеров](tickets/004-agent-registry.md) — Экземпляр пересмотрен: **долгоживущий агент Репозитория** (один на Сборка+repo, один чекпоинт-тред, копит знание; События и чат — в него), статусы down/running (single-running инвариант), опускание по idle-таймауту; чат пользователя — только через backend с прокси в API раннера; Сборка = llm+sandbox connections+промпт+пресет+лимиты; раннер — саморегистрация+heartbeat+слоты.

- [Схема БД v1 + миграции](tickets/006-db-schema.md) — одна база `git_agent`, backend в Postgres-схеме `hub.*`; 15 таблиц ([001_init.sql](../migrations/backend/001_init.sql), [ERD](../migrations/backend/ERD.md)); мигратор — нумерованные SQL + `backend/cmd/migrate` (`task backend:migrate`); применено и идемпотентно.
- [Топология RabbitMQ](tickets/005-rabbit-topology.md) — свой rabbitmq:4 в deploy (порты 5673/15673); topic exchange `events` (`provider.repo.action`), одна durable-очередь `#`, competing consumers; outbox-паблишер с publisher confirm (at-least-once), ре-публикация по heartbeat-таймауту раннера.

- [HTTP-поверхность backend v1](tickets/009-http-surface.md) — полный контракт в `backend/docs/openapi.yaml`: auth/связки, репозитории+вебхук-приёмник `/hooks/{provider}/{repoId}`, сборки/подключения, экземпляры (chat SSE), раннеры (`X-Runner-Token`).
- [Контракты между сервисами](tickets/010-service-contracts.md) — Экземпляр резолвит backend на вебхуке (в Событии готовые instanceId/threadId); событие для поднятого Экземпляра форвардится держателю по HTTP; API раннера: raise/events/chat(SSE)/stop/health + регистрация и heartbeat в backend; тулзы report_finding/write_report → hub.findings/reports; везде camelCase + OpenAPI.

- [Профили агентов](tickets/011-agent-profiles.md) — подписки Сборок: тип действия + маска ветки, таблица `build_subscriptions` (N:M, миграция 002) вместо `repositories.build_id`, фолбэк — дефолтная Сборка; веер: одно Событие → Экземпляры всех совпавших Сборок; раннеры универсальные.

## Not yet specified

- Фильтр подписки по путям в diff («тронули src/auth/») — следующий шаг профилей.
- «Сборка → пул раннеров» (тяжёлые Сборки на толстом сервере) — если упрёмся в железо.
- Деплой: сервис в deploy/docker-compose.yml — добавить сам Go-сервис (Rabbit решён в 005).
- Отношение фронтенда к новому сервису (сейчас фронт ходит в Python-gateway).

## Out of scope

- ~~Профили агентов~~ — втащены в скоуп (тикет 011) по решению пользователя после прохождения основной карты.
- Перевод Python-агента на консьюмер RabbitMQ — «пока не трогай агента»; отдельное усилие после этой карты.
- Polling как механизм мониторинга — выбраны webhooks.
