-- Раны становятся claim-абельными, арендуемыми, отменяемыми, возобновляемыми.
ALTER TABLE runs
    ADD COLUMN stop_reason TEXT,
    ADD COLUMN cancel_requested_at TIMESTAMPTZ,
    ADD COLUMN owner_worker_id TEXT,
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN attempt INT NOT NULL DEFAULT 1,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE runs ALTER COLUMN status SET DEFAULT 'pending';
ALTER TABLE runs DROP CONSTRAINT runs_status_check;
ALTER TABLE runs ADD CONSTRAINT runs_status_check
    CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'interrupted'));

-- Идентичность Рана == ключ идемпотентности (глоссарий: один Ран на (коммит, модель)).
CREATE UNIQUE INDEX runs_identity_uq ON runs (repository_id, commit_sha, llm_model);
-- Скан жнеца сирот.
CREATE INDEX runs_active_idx ON runs (id) WHERE status IN ('pending', 'running');
-- Курсорная пагинация durable-истории (run_events.id — это seq).
CREATE INDEX run_events_run_id_id_idx ON run_events (run_id, id);
