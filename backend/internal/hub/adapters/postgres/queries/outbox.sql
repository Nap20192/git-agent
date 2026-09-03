-- Ingest вебхука (одна транзакция в Store.Ingest) и transactional outbox

-- name: InsertEvent :one
INSERT INTO hub.events (provider, delivery_id, repository_id, action, commit_sha, ref, payload, trace_id,
                        before_sha, base_sha, head_sha, pr_number, pr_title, pr_body, changed_files)
VALUES (@provider, @delivery_id, @repository_id, @action,
        NULLIF(@commit_sha::text, ''), NULLIF(@ref::text, ''), @payload, @trace_id,
        NULLIF(@before_sha::text, ''), NULLIF(@base_sha::text, ''), NULLIF(@head_sha::text, ''),
        NULLIF(@pr_number::int, 0), NULLIF(@pr_title::text, ''), NULLIF(@pr_body::text, ''), @changed_files)
ON CONFLICT (provider, delivery_id) DO NOTHING
RETURNING id;

-- name: UpsertInstance :one
INSERT INTO hub.agent_instances (build_id, repository_id, thread_id)
VALUES (@build_id, @repository_id, @thread_id)
ON CONFLICT (build_id, repository_id) DO UPDATE SET updated_at = now()
RETURNING id, thread_id;

-- name: InsertInstanceEvent :exec
INSERT INTO hub.instance_events (instance_id, event_id, dedup_key)
VALUES (@instance_id, @event_id, @dedup_key) ON CONFLICT DO NOTHING;

-- name: InsertOutbox :exec
INSERT INTO hub.outbox (event_id, routing_key, payload) VALUES (@event_id, @routing_key, @payload);

-- name: Unpublished :many
SELECT id, routing_key, payload FROM hub.outbox
 WHERE published_at IS NULL ORDER BY id LIMIT @row_limit::int;

-- name: MarkPublished :exec
UPDATE hub.outbox SET published_at = now() WHERE id = @id;
