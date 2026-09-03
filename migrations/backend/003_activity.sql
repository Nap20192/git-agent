-- Activity-журнал хода (тикет 012): кадры графа Рана per (Экземпляр, ход).
-- Пишет раннер; hub читает для реплея down-Экземпляров. event_id NULL — ход чата.

CREATE TABLE hub.activity (
    id          BIGSERIAL PRIMARY KEY,
    instance_id BIGINT      NOT NULL REFERENCES hub.agent_instances ON DELETE CASCADE,
    event_id    BIGINT      REFERENCES hub.events ON DELETE CASCADE,
    seq         INT         NOT NULL,
    kind        TEXT        NOT NULL,
    payload     JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX activity_turn ON hub.activity (instance_id, event_id, seq);
