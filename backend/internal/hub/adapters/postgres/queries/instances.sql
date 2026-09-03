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
SELECT id, instance_id, event_id, summary, created_at, structured
  FROM hub.reports WHERE instance_id = @instance_id ORDER BY id DESC;

-- Находки v2 (миграция 007): скоуп — Экземпляр либо Репозиторий (все его
-- Экземпляры), фильтры — NULL = без фильтра.
-- name: Findings :many
SELECT f.* FROM hub.findings f
  JOIN hub.agent_instances i ON i.id = f.instance_id
 WHERE (sqlc.narg('instance_id')::bigint IS NULL OR f.instance_id = sqlc.narg('instance_id'))
   AND (sqlc.narg('repository_id')::bigint IS NULL OR i.repository_id = sqlc.narg('repository_id'))
   AND (sqlc.narg('severity')::text IS NULL OR f.severity = sqlc.narg('severity'))
   AND (sqlc.narg('category')::text IS NULL OR f.category = sqlc.narg('category'))
   AND (sqlc.narg('event_id')::bigint IS NULL OR f.event_id = sqlc.narg('event_id'))
   AND (sqlc.narg('introduced_by')::text IS NULL OR f.introduced_by = sqlc.narg('introduced_by'))
 ORDER BY f.id DESC;

-- name: SetInstanceRunning :exec
UPDATE hub.agent_instances
   SET status = 'running', runner_id = @runner_id::bigint, updated_at = now() WHERE id = @id;

-- name: SetInstanceDown :exec
UPDATE hub.agent_instances
   SET status = 'down', runner_id = NULL, updated_at = now() WHERE id = @id;

-- Messages — транскрипт чата Экземпляра (история как в ChatGPT): реплики
-- (chat_user/chat_agent), карточки ходов по Событиям (run_started/run_finished с
-- event_id) и ошибки ходов; курсор — id (before), новые первыми.
-- name: Messages :many
SELECT a.id, a.event_id, a.kind, a.payload, a.created_at, a.trace_id, e.action, e.commit_sha
  FROM hub.activity a
  LEFT JOIN hub.events e ON e.id = a.event_id
 WHERE a.instance_id = @instance_id
   AND (a.kind IN ('chat_user', 'chat_agent', 'run_failed')
        OR (a.kind IN ('run_started', 'run_finished') AND a.event_id IS NOT NULL))
   AND (sqlc.narg('before')::bigint IS NULL OR a.id < sqlc.narg('before')::bigint)
 ORDER BY a.id DESC
 LIMIT @lim;
