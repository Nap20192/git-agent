-- hub: схема Go-бекенда (см. .wayfinder/map.md). Секретные поля *_enc — AES-GCM ключом из env.

CREATE SCHEMA IF NOT EXISTS hub;

-- Вход и пользователи -------------------------------------------------------

CREATE TABLE hub.users (
    id           BIGSERIAL PRIMARY KEY,
    display_name TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hub.sessions (
    token      TEXT PRIMARY KEY,
    user_id    BIGINT      NOT NULL REFERENCES hub.users ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- OAuth-связки: вход и доступ к репозиториям; аккаунтов одного провайдера может быть несколько
CREATE TABLE hub.identities (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT      NOT NULL REFERENCES hub.users ON DELETE CASCADE,
    provider          TEXT        NOT NULL CHECK (provider IN ('github', 'gitlab')),
    provider_user_id  TEXT        NOT NULL,
    username          TEXT        NOT NULL,
    access_token_enc  BYTEA       NOT NULL,
    refresh_token_enc BYTEA,
    token_expires_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_user_id)
);

-- Подключения и Сборки ------------------------------------------------------

CREATE TABLE hub.llm_connections (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES hub.users ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    api_base    TEXT        NOT NULL,
    api_key_enc BYTEA       NOT NULL,
    model       TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- endpoint сервиса OpenSandbox
CREATE TABLE hub.sandbox_connections (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT        NOT NULL UNIQUE,
    domain      TEXT        NOT NULL,
    api_key_enc BYTEA,
    image       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Сборка Агента: хранимое определение (CONTEXT.md)
CREATE TABLE hub.agent_builds (
    id                    BIGSERIAL PRIMARY KEY,
    user_id               BIGINT      NOT NULL REFERENCES hub.users ON DELETE CASCADE,
    name                  TEXT        NOT NULL,
    llm_connection_id     BIGINT      NOT NULL REFERENCES hub.llm_connections,
    sandbox_connection_id BIGINT      NOT NULL REFERENCES hub.sandbox_connections,
    prompt                TEXT,
    memory_preset         TEXT,
    limits                JSONB       NOT NULL DEFAULT '{}',
    is_default            BOOLEAN     NOT NULL DEFAULT false,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

-- Репозитории и События -----------------------------------------------------

CREATE TABLE hub.repositories (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT      NOT NULL REFERENCES hub.users ON DELETE CASCADE,
    identity_id         BIGINT      NOT NULL REFERENCES hub.identities,
    provider            TEXT        NOT NULL CHECK (provider IN ('github', 'gitlab')),
    external_id         TEXT        NOT NULL,
    owner               TEXT        NOT NULL,
    name                TEXT        NOT NULL,
    default_branch      TEXT,
    webhook_provider_id TEXT,
    webhook_secret_enc  BYTEA,
    build_id            BIGINT      REFERENCES hub.agent_builds,
    connected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider, external_id)
);

-- журнал всего, что пришло с вебхуков; payload — для отладки
CREATE TABLE hub.events (
    id            BIGSERIAL PRIMARY KEY,
    provider      TEXT        NOT NULL,
    delivery_id   TEXT        NOT NULL,
    repository_id BIGINT      NOT NULL REFERENCES hub.repositories ON DELETE CASCADE,
    action        TEXT        NOT NULL,
    commit_sha    TEXT,
    ref           TEXT,
    payload       JSONB       NOT NULL,
    received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, delivery_id)
);

-- transactional outbox: единственный путь в RabbitMQ; published_at ставится после confirm
CREATE TABLE hub.outbox (
    id           BIGSERIAL PRIMARY KEY,
    event_id     BIGINT      NOT NULL REFERENCES hub.events ON DELETE CASCADE,
    routing_key  TEXT        NOT NULL,
    payload      JSONB       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);

CREATE INDEX outbox_unpublished ON hub.outbox (id) WHERE published_at IS NULL;

-- Песочницы, Экземпляры, раннеры --------------------------------------------

CREATE TABLE hub.sandbox_instances (
    id                    BIGSERIAL PRIMARY KEY,
    external_id           TEXT        NOT NULL,
    sandbox_connection_id BIGINT      NOT NULL REFERENCES hub.sandbox_connections,
    status                TEXT        NOT NULL DEFAULT 'alive' CHECK (status IN ('alive', 'dead')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    killed_at             TIMESTAMPTZ
);

CREATE TABLE hub.runners (
    id                BIGSERIAL PRIMARY KEY,
    name              TEXT        NOT NULL UNIQUE,
    address           TEXT        NOT NULL,
    slots             INT         NOT NULL,
    registered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Экземпляр Агента: долгоживущий агент репозитория (CONTEXT.md);
-- у Экземпляра одна песочница, песочницу могут делить несколько Экземпляров
CREATE TABLE hub.agent_instances (
    id                  BIGSERIAL PRIMARY KEY,
    build_id            BIGINT      NOT NULL REFERENCES hub.agent_builds,
    repository_id       BIGINT      NOT NULL REFERENCES hub.repositories ON DELETE CASCADE,
    sandbox_instance_id BIGINT      REFERENCES hub.sandbox_instances,
    thread_id           TEXT        NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'down' CHECK (status IN ('down', 'running')),
    runner_id           BIGINT      REFERENCES hub.runners ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (build_id, repository_id),
    CHECK (status = 'down' OR runner_id IS NOT NULL)
);

-- журнал обработанных Событий: дедуп (dedup_key = commit_sha либо event_id) и ре-публикация
CREATE TABLE hub.instance_events (
    instance_id  BIGINT      NOT NULL REFERENCES hub.agent_instances ON DELETE CASCADE,
    event_id     BIGINT      NOT NULL REFERENCES hub.events ON DELETE CASCADE,
    dedup_key    TEXT        NOT NULL,
    processed_at TIMESTAMPTZ,
    PRIMARY KEY (instance_id, dedup_key)
);

-- Результаты (пишет агент тулзой) -------------------------------------------

CREATE TABLE hub.reports (
    id          BIGSERIAL PRIMARY KEY,
    instance_id BIGINT      NOT NULL REFERENCES hub.agent_instances ON DELETE CASCADE,
    event_id    BIGINT      REFERENCES hub.events,
    summary     TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hub.findings (
    id          BIGSERIAL PRIMARY KEY,
    instance_id BIGINT      NOT NULL REFERENCES hub.agent_instances ON DELETE CASCADE,
    report_id   BIGINT      REFERENCES hub.reports ON DELETE SET NULL,
    severity    TEXT        NOT NULL,
    cwe         TEXT,
    cve         TEXT,
    file        TEXT,
    line_start  INT,
    line_end    INT,
    evidence    TEXT,
    remediation TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX findings_instance ON hub.findings (instance_id);
CREATE INDEX events_repository ON hub.events (repository_id);
