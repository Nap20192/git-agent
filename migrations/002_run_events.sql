CREATE TABLE run_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES runs (id),
    kind TEXT NOT NULL,  -- agent_start | model_message | tool_call | agent_finish
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX run_events_run_id_idx ON run_events (run_id);
