-- Живые/мёртвые Экземпляры Сэндбокса (в отличие от таблицы sandboxes — пресетов).
-- Сэндбоксы создаются без TTL и живут до явного убийства; здесь их учёт.
CREATE TABLE sandbox_instances (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,   -- id сэндбокса в OpenSandbox
    kind TEXT NOT NULL,                 -- opensandbox (local не учитывается)
    image TEXT,
    run_id BIGINT REFERENCES runs (id), -- Ран-создатель
    status TEXT NOT NULL DEFAULT 'alive' CHECK (status IN ('alive', 'dead')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    killed_at TIMESTAMPTZ
);

-- resume ищет живой Экземпляр Рана: WHERE run_id=? AND status='alive'
CREATE INDEX sandbox_instances_run_alive ON sandbox_instances (run_id)
WHERE status = 'alive';
