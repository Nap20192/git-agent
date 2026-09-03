-- Экземпляры Агента, Сэндбоксы, activity, результаты

-- name: Instances :many
SELECT i.id, i.build_id, i.repository_id, i.sandbox_instance_id,
       si.external_id AS sandbox_external_id, si.status AS sandbox_status,
       i.thread_id, i.status, i.runner_id, i.updated_at
  FROM hub.agent_instances i
  JOIN hub.repositories r ON r.id = i.repository_id
  LEFT JOIN hub.sandbox_instances si ON si.id = i.sandbox_instance_id
 WHERE r.user_id = @user_id
   AND (sqlc.narg('repository_id')::bigint IS NULL OR i.repository_id = sqlc.narg('repository_id'))
 ORDER BY i.id;

-- name: Instance :one
SELECT i.id, i.build_id, i.repository_id, i.sandbox_instance_id,
       si.external_id AS sandbox_external_id, si.status AS sandbox_status,
       i.thread_id, i.status, i.runner_id, i.updated_at
  FROM hub.agent_instances i
  JOIN hub.repositories r ON r.id = i.repository_id
  LEFT JOIN hub.sandbox_instances si ON si.id = i.sandbox_instance_id
 WHERE i.id = @id AND r.user_id = @user_id;

-- Activity — реплей activity-кадров хода (тикет 012); NULL event_id = ход чата.
-- name: ActivityByEvent :many
SELECT payload FROM hub.activity
 WHERE instance_id = @instance_id AND event_id IS NOT DISTINCT FROM sqlc.narg('event_id')::bigint
 ORDER BY seq, id;

-- Последний ход: группа event_id самой свежей строки.
-- name: ActivityLatest :many
SELECT a.payload FROM hub.activity a
 WHERE a.instance_id = @instance_id AND a.event_id IS NOT DISTINCT FROM
       (SELECT b.event_id FROM hub.activity b WHERE b.instance_id = @instance_id ORDER BY b.id DESC LIMIT 1)
 ORDER BY a.seq, a.id;

-- name: SandboxInstances :many
SELECT id, external_id, sandbox_connection_id, status, created_at, killed_at
  FROM hub.sandbox_instances ORDER BY id DESC;

-- name: SandboxInstance :one
SELECT id, external_id, sandbox_connection_id, status, created_at, killed_at
  FROM hub.sandbox_instances WHERE id = @id;

-- name: CreateSandboxInstance :one
INSERT INTO hub.sandbox_instances (external_id, sandbox_connection_id)
VALUES (@external_id, @sandbox_connection_id) RETURNING id;

-- name: MarkSandboxInstanceDead :exec
UPDATE hub.sandbox_instances SET status = 'dead', killed_at = now() WHERE id = @id;

-- name: LinkInstanceSandbox :execrows
UPDATE hub.agent_instances i SET sandbox_instance_id = @sandbox_instance_id::bigint, updated_at = now()
  FROM hub.repositories r
 WHERE i.id = @id AND r.id = i.repository_id AND r.user_id = @user_id;

-- name: Reports :many
SELECT id, instance_id, event_id, summary, created_at
  FROM hub.reports WHERE instance_id = @instance_id ORDER BY id DESC;

-- name: Findings :many
SELECT id, instance_id, report_id, severity, cwe, cve, file, line_start, line_end,
       evidence, remediation, created_at
  FROM hub.findings WHERE instance_id = @instance_id ORDER BY id DESC;

-- name: SetInstanceRunning :exec
UPDATE hub.agent_instances
   SET status = 'running', runner_id = @runner_id::bigint, updated_at = now() WHERE id = @id;

-- name: SetInstanceDown :exec
UPDATE hub.agent_instances
   SET status = 'down', runner_id = NULL, updated_at = now() WHERE id = @id;
