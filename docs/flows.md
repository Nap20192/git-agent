# Потоки git-agent hub — sequence-диаграммы

Каждый поток — с ветками ошибок (`alt/else`). Термины — CONTEXT.md. Рендер в PNG: `task diagrams`
(mermaid-cli). Источник правды по контрактам — `backend/docs/openapi.yaml`, тикет 010 (Rabbit/раннер).

trace_id: `X-Trace-Id` на всех HTTP-стрелках (фронт → hub → раннер/провайдер/OpenSandbox, эхо в ответе), `traceId` в Rabbit-сообщении, колонки `hub.events.trace_id` / `hub.activity.trace_id`; тот же id — поле `trace_id` в логах hub/раннера и тег `trace:<id>` в Langfuse/LangSmith.

## 1. Вход через GitHub/GitLab (OAuth)

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant F as Frontend
    participant H as hub
    participant G as GitHub OAuth
    participant DB as Postgres (hub.*)

    Note over U,DB: ФАЗА 1 — ВХОД
    U->>F: «continue with github»
    F->>H: GET /api/auth/github/login
    alt OAuth-ключи не заданы
        H-->>F: 503 provider not configured
    else ok
        H->>H: state (anti-CSRF) → cookie hub_oauth_state
        H-->>U: 302 → github.com/login/oauth/authorize?redirect_uri=OAUTH_REDIRECT_BASE/callback
    end
    U->>G: авторизует приложение
    G-->>H: GET /api/auth/github/callback?code&state
    alt state ≠ cookie
        H-->>U: 400 invalid oauth state
    else redirect_uri ≠ зарегистрированному в OAuth App
        G-->>H: error redirect_uri mismatch
        H-->>U: 500 (лог: oauth callback failed)
    else DNS/сеть до github.com
        H-->>U: 500 exchange code: dial tcp lookup ... no such host
    else ok
        H->>G: POST /login/oauth/access_token
        G-->>H: access_token
        H->>G: GET api.github.com/user
        G-->>H: профиль (id, login)
        Note over H,DB: upsert identities (unique provider+provider_user_id),<br/>токен — AES-GCM(SECRETS_KEY) · без сессии = вход, с сессией = добавить связку (409 если чужая)
        H->>DB: INSERT users? / identities / sessions
        H-->>U: 302 FRONTEND_URL + cookie hub_session (httpOnly)
    end
```

## 2. Подключение репозитория (webhook ставит hub / watch по URL)

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant F as Frontend
    participant H as hub
    participant G as GitHub API
    participant DB as Postgres

    Note over U,DB: ФАЗА 2 — ПОДКЛЮЧЕНИЕ РЕПО
    U->>F: drawer «connect repository», выбор связки
    F->>H: GET /api/identities/{id}/repos
    H->>G: GET /user/repos (токен связки)
    alt DNS не резолвит api.github.com
        H-->>F: 500 lookup api.github.com: no such host
    else токен протух (GitLab)
        H->>G: refresh_token → новый access
        G-->>H: ok
    else ok
        G-->>H: список репо
        H-->>F: [ProviderRepo]
    end
    alt hook: свой репо через связку
        U->>F: «connect →»
        F->>H: POST /api/repositories {identityId, externalId}
        H->>DB: INSERT repositories (mode=hook, секрет хука AES-GCM, id нужен для URL)
        H->>G: POST /repos/{o}/{r}/hooks {url: WEBHOOK_BASE_URL/hooks/github/{id}, secret, events:*}
        alt нет admin-прав на репо
            G-->>H: 404 Not Found
            H->>DB: DELETE repositories (rollback)
            H-->>F: 404 create provider hook: not found
        else URL не публичный (localhost)
            G-->>H: 422 url isn't reachable over the public Internet
            H->>DB: rollback
            H-->>F: 502 → нужен туннель/релей (WEBHOOK_BASE_URL)
        else ok
            G-->>H: hook id
            H->>DB: UPDATE repositories.webhook_provider_id
            H-->>F: 201 Repository (default-Сборка подхватит события, пока нет подписок)
        end
    else watch: чужой публичный репо по URL (тикет 015)
        U->>F: «public repository URL» → «connect →»
        F->>H: POST /api/repositories {url: https://github.com/{o}/{r}}
        Note over H: провайдер — по хосту (github.com / gitlab.com)
        H->>G: GET /repos/{o}/{r} (публичный API, без токена)
        alt хост/путь не разобрать
            H-->>F: 400 url must be https://github.com/{owner}/{repo} …
        else приватный или не существует
            G-->>H: private:true / 404
            H-->>F: 422 repository is private or not found
        else ok
            G-->>H: id, owner, name, default_branch
            H->>DB: INSERT repositories (mode=watch, identity_id/хук/секрет = NULL)
            H-->>F: 201 Repository {mode: watch} — бейдж «watch», вебхука нет, запуск руками (/trigger: HEAD публичным API)
        end
    end
```

## 3. Вебхук → outbox → RabbitMQ (fan-out)

```mermaid
sequenceDiagram
    participant G as GitHub
    participant R as relay (Railway) / cloudflared
    participant H as hub
    participant DB as Postgres
    participant MQ as RabbitMQ

    Note over G,MQ: ФАЗА 3 — ПРИЁМ СОБЫТИЯ (наружу ВСЕГДА 200)
    G->>R: POST /hooks/github/{repoId} + X-Hub-Signature-256
    R-->>H: переигрывает (puller, путь+заголовки сохранены)
    H->>DB: SELECT repositories WHERE id
    alt репо неизвестен / отключён
        H-->>G: 200 (лог: dropped, unknown repository)
    else подпись HMAC не сошлась
        H-->>G: 200 (лог: dropped, invalid signature)
    else повторная доставка (unique provider+delivery_id)
        H-->>G: 200 (лог: duplicate delivery)
    else ok
        Note over H,DB: одна транзакция
        H->>DB: INSERT hub.events (журнал, payload jsonb)
        H->>DB: SELECT build_subscriptions WHERE repo (actions ∋ action, ref ~ ref_mask)
        alt подписок нет
            H->>DB: default-Сборка на всё
        end
        loop каждая совпавшая Сборка
            H->>DB: UPSERT agent_instances (build, repo) — один Экземпляр на пару
            H->>DB: INSERT outbox {eventId, instanceId, threadId, dedupKey}
        end
        H-->>G: 200
    end
    Note over H,MQ: outbox-паблишер (фон)
    loop батчами
        H->>MQ: publish exchange=events, key=github.{repo}.{action}
        alt Rabbit недоступен
            MQ-->>H: connect error → published_at остаётся NULL, повтор
        else confirm
            MQ-->>H: ack
            H->>DB: UPDATE outbox.published_at
        end
    end
```

## 4. Раннер: обработка События агентом

```mermaid
sequenceDiagram
    participant MQ as RabbitMQ
    participant RN as Раннер
    participant DB as Postgres
    participant SB as OpenSandbox
    participant LLM as LLM
    participant H as hub

    Note over MQ,H: ФАЗА 4 — ИСПОЛНЕНИЕ (гарантии = БД + чекпоинты, auto-ack)
    MQ->>RN: Событие {eventId, instanceId, threadId, dedupKey…}
    alt сообщение не парсится
        RN-->>MQ: drop (лог unparseable)
    end
    RN->>DB: INSERT instance_events (instance, dedupKey) — дедуп
    alt уже обработано (processed_at NOT NULL)
        RN-->>MQ: skip
    end
    RN->>DB: CAS agent_instances down→running, runner_id=я
    alt Экземпляр running у другого раннера
        RN->>RN: POST http://holder/instances/{id}/events (форвард)
    else слоты заняты
        RN->>RN: ждёт слот (FIFO)
    end
    RN->>DB: JOIN Сборка → llm/sandbox connections (расшифровка ключей)
    RN->>SB: connect(external_id)
    alt песочница не привязана / dead
        RN-->>DB: run_failed «sandbox not provisioned» (processed_at NULL — «Продолжить» после создания)
    else контейнер исчез
        RN->>DB: sandbox_instances.status=dead
        RN-->>DB: run_failed
    else ok
        RN->>SB: git clone / fetch + checkout commitSha
        alt git не достучался (DNS/сеть)
            RN-->>DB: run_failed (событие не потеряно, ре-публикация повторит)
        end
        Note over RN,LLM: Лид: план → task(Сабагенты, лимиты Сборки) → квитанции
        loop ходы Лида/Сабагентов
            RN->>LLM: chat/completions
            alt 402 / 429 / timeout
                LLM-->>RN: error → run_failed, шаг откатывается к чекпоинту
            else ok
                LLM-->>RN: tool calls
                RN->>SB: sandbox.run(cmd) (лог длительности)
                RN->>DB: report_finding → hub.findings
                RN->>DB: activity (task_started/finished, node) — SSE в Playground
            end
        end
        RN->>DB: write_report → hub.reports · processed_at = now
        RN->>DB: idle-таймаут → status=down (чекпоинт и песочница живут)
    end
    Note over RN,H: heartbeat каждые N с · раннер умер → hub: Экземпляры→down, необработанные События → снова в outbox → другой раннер продолжает с чекпоинта
```

## 5. Ручной запуск / полный скан

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant H as hub
    participant G as GitHub API
    participant DB as Postgres

    U->>H: POST /api/repositories/{id}/trigger {mode: manual|full, ref?, commitSha?}
    alt commitSha не задан
        H->>G: GET /repos/{o}/{r}/commits/{ref}
        alt DNS/сеть
            G-->>H: error → 500 resolve "main" head
        else
            G-->>H: sha
        end
    end
    alt mode=manual, коммит уже запускали
        H-->>U: 202 {duplicate:true, instanceIds:[]}
    else mode=manual
        H->>DB: Событие action=manual (delivery manual-{repo}-{sha}) → fan-out как вебхук
        H-->>U: 202 {commitSha, instanceIds}
    else mode=full
        Note over H,DB: не привязан к коммиту: delivery уникален на клик, dedupKey=full-{eventId}
        H->>DB: Событие action=full_scan → fan-out
        H-->>U: 202 (Лид получает промпт полного аудита: план областей → веер Сабагентов)
    end
```

## 6. Чат с агентом и обрыв клиента

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant H as hub
    participant RN as Раннер
    participant LLM as LLM

    U->>H: POST /api/instances/{id}/chat {message} (SSE)
    alt Экземпляр down
        H->>RN: POST /instances/{id}/raise
        alt слотов нет
            RN-->>H: 202 queued (поднимет фоном) → фронт «в очереди за слотом»
        else нет песочницы
            RN-->>H: 409 sandbox not provisioned
        else
            RN-->>H: 200 running
        end
    end
    H->>RN: POST /instances/{id}/chat (прокси, ждём первый байт ≤ CHAT_FIRST_BYTE_TIMEOUT)
    RN->>LLM: ход в тред Экземпляра (чекпоинт)
    loop кадры ChatEvent {kind: token|activity|done}
        RN-->>H: SSE
        H-->>U: SSE
    end
    alt клиент закрыл вкладку
        U--xH: соединение оборвано
        H-->>RN: context canceled (INFO «stream closed by client»)
        Note over RN: ход отменяется (CancelledError) — недописанный шаг теряется.<br/>TODO: исполнять ход в фоне независимо от клиента
    else таймаут первого байта
        H-->>U: 504
    end
```

## 7. Остановить ход / продолжить

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant H as hub
    participant RN as Раннер
    participant DB as Postgres
    participant MQ as RabbitMQ

    U->>H: POST /api/instances/{id}/stop
    H->>RN: POST /instances/{id}/stop
    RN->>RN: cancel asyncio-таска хода (CancelledError — штатно)
    RN->>DB: CAS running→down (только со своим runner_id) · processed_at НЕ ставится
    RN-->>H: 204 (слот свободен, чекпоинт хранит завершённые шаги)
    U->>H: POST /api/instances/{id}/resume
    H->>DB: instance_events WHERE processed_at IS NULL
    alt нечего продолжать
        H-->>U: 200 {eventIds: []}
    else
        H->>DB: INSERT outbox (ре-публикация, тот же код что heartbeat-воркер)
        H-->>U: 200 {eventIds}
        H->>MQ: publish
        MQ->>RN: Событие → клейм → LangGraph продолжает с чекпоинта
    end
```

## 8. Жизненный цикл песочницы (создаёт юзер или hub при запуске, раннер только connect)

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant H as hub
    participant SB as OpenSandbox :8090
    participant DB as Postgres
    participant RN as Раннер

    U->>H: POST /api/sandbox-instances {sandboxConnectionId}
    H->>DB: sandbox_connections (domain, api_key_enc, image)
    H->>SB: POST /v1/sandboxes {image, entrypoint: tail -f /dev/null, resourceLimits, timeout: null}
    alt домен с пробелом / OpenSandbox лежит
        SB-->>H: connect error → 500
    else 422 (нет entrypoint/resourceLimits)
        SB-->>H: validation error → 500 (исправлено в клиенте)
    else 202
        SB-->>H: {id}
        H->>DB: INSERT sandbox_instances (external_id, alive)
        H-->>U: 201
    end
    U->>H: POST /api/instances/{id}/sandbox {sandboxInstanceId}
    H->>DB: agent_instances.sandbox_instance_id
    Note over U,DB: запуск: /trigger (каждый затронутый Экземпляр), raise, chat
    U->>H: POST /api/repositories/{id}/trigger | /api/instances/{id}/raise | /chat
    H->>DB: Экземпляр (upsert) + статус привязанной песочницы
    alt нет живой (не привязана / dead) — hub создаёт сам
        H->>DB: agent_builds.sandbox_connection_id Сборки Экземпляра
        H->>SB: POST /v1/sandboxes (тот же путь, что ручное создание)
        alt OpenSandbox не ответил
            SB-->>H: error
            H-->>U: 502 provision sandbox for instance: … (Событие НЕ публикуется, raise не зовётся)
        else 202
            SB-->>H: {id}
            H->>DB: INSERT sandbox_instances (alive) + agent_instances.sandbox_instance_id
        end
    else живая привязана
        Note over H: вторую не создаём
    end
    H->>DB: Событие в outbox / H->>RN: raise
    Note over RN,SB: при подъёме Экземпляра
    RN->>SB: Sandbox.connect(external_id)
    alt контейнер исчез (рестарт докера), статус ещё alive
        RN-->>H: SandboxNotProvisionedError → Событие не обработано; юзер kill → dead, следующий запуск пересоздаст
    else ok
        RN->>SB: commands.run(…) ~1с/команда
    end
    U->>H: DELETE /api/sandbox-instances/{id}
    H->>SB: DELETE /v1/sandboxes/{id}
    H->>DB: status=dead, killed_at
```
