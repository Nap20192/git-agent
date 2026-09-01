CREATE TABLE sandboxes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('opensandbox', 'local', 'ssh')),
    image TEXT,    -- для opensandbox
    workdir TEXT,  -- для local
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO sandboxes (name, kind, image, workdir) VALUES
    ('git', 'opensandbox', 'alpine/git:latest', NULL),
    ('python', 'opensandbox', 'python:3.12-slim', NULL),
    ('local', 'local', NULL, '/tmp/git-agent-work');

ALTER TABLE runs ADD COLUMN sandbox_id BIGINT REFERENCES sandboxes (id);
