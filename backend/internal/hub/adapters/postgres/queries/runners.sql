-- Раннеры и надзор за heartbeat

-- name: UpsertRunner :one
INSERT INTO hub.runners (name, address, slots)
VALUES (@name, @address, @slots)
ON CONFLICT (name) DO UPDATE
  SET address = @address, slots = @slots, last_heartbeat_at = now()
RETURNING id;

-- name: HeartbeatRunner :execrows
UPDATE hub.runners SET last_heartbeat_at = now() WHERE id = @id;

-- name: Runners :many
SELECT id, name, address, slots, last_heartbeat_at FROM hub.runners ORDER BY id;

-- name: Runner :one
SELECT id, name, address, slots, last_heartbeat_at FROM hub.runners WHERE id = @id;

-- name: AliveRunner :one
SELECT id, name, address, slots, last_heartbeat_at
  FROM hub.runners
 WHERE last_heartbeat_at > now() - @alive_within::interval
 ORDER BY last_heartbeat_at DESC LIMIT 1;

-- Ре-публикация (heartbeat + resume): незавершённые События (instance_events без
-- processed_at) Экземпляров из CTE targets(id) — новыми строками outbox;
-- routing_key/payload копируются из исходной публикации ЭТОГО Экземпляра
-- (по instanceId в payload — при веере одного События на несколько Экземпляров
-- строки outbox различаются). SQL продублирован в двух запросах ниже: sqlc не
-- умеет композицию фрагментов.

-- RequeueStale — один стейтмент: running-Экземпляры протухших Раннеров → down,
-- их необработанные События — снова в outbox.
-- name: RequeueStale :one
WITH targets AS (
    UPDATE hub.agent_instances SET status = 'down', runner_id = NULL, updated_at = now()
     WHERE status = 'running'
       AND runner_id IN (SELECT id FROM hub.runners WHERE last_heartbeat_at < now() - @timeout::interval)
     RETURNING id
), requeued AS (
    INSERT INTO hub.outbox (event_id, routing_key, payload)
    SELECT ie.event_id, o.routing_key, o.payload
      FROM hub.instance_events ie
      JOIN targets t ON t.id = ie.instance_id
      JOIN LATERAL (SELECT routing_key, payload FROM hub.outbox o2
                     WHERE o2.event_id = ie.event_id
                       AND (o2.payload->>'instanceId')::bigint = ie.instance_id
                     ORDER BY o2.id LIMIT 1) o ON true
     WHERE ie.processed_at IS NULL
     RETURNING event_id, coalesce(payload->>'traceId', '') AS trace_id
)
SELECT (SELECT count(*) FROM targets)::int AS downed,
       (SELECT coalesce(array_agg(trace_id), '{}') FROM requeued)::text[] AS requeued_trace_ids;

-- RequeueInstance — «Продолжить»: незавершённые События одного Экземпляра —
-- снова в outbox; возвращает пере-опубликованные eventId (пусто = нечего продолжать).
-- name: RequeueInstance :many
WITH targets AS (SELECT @instance_id::bigint AS id)
INSERT INTO hub.outbox (event_id, routing_key, payload)
SELECT ie.event_id, o.routing_key, o.payload
  FROM hub.instance_events ie
  JOIN targets t ON t.id = ie.instance_id
  JOIN LATERAL (SELECT routing_key, payload FROM hub.outbox o2
                 WHERE o2.event_id = ie.event_id
                   AND (o2.payload->>'instanceId')::bigint = ie.instance_id
                 ORDER BY o2.id LIMIT 1) o ON true
 WHERE ie.processed_at IS NULL
 RETURNING event_id;
