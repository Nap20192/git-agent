-- Профили агентов (тикет 011): подписки Сборок на события Репозитория.
-- Заменяет repositories.build_id (1:1) на N:M с фильтром action+ref_mask;
-- данные переносятся, колонка дропается.

CREATE TABLE hub.build_subscriptions (
    id            BIGSERIAL PRIMARY KEY,
    build_id      BIGINT NOT NULL REFERENCES hub.agent_builds ON DELETE CASCADE,
    repository_id BIGINT NOT NULL REFERENCES hub.repositories ON DELETE CASCADE,
    actions       TEXT[] NOT NULL DEFAULT '{}', -- пустой массив = все действия
    ref_mask      TEXT,                         -- NULL = любой ref; glob-маска ("release/*")
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (build_id, repository_id)
);

CREATE INDEX build_subscriptions_repository ON hub.build_subscriptions (repository_id);

INSERT INTO hub.build_subscriptions (build_id, repository_id)
SELECT build_id, id FROM hub.repositories WHERE build_id IS NOT NULL;

ALTER TABLE hub.repositories DROP COLUMN build_id;
