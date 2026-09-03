-- Репозитории, События, подписки Сборок (тикет 011)

-- name: FindRepository :one
SELECT user_id, owner, name, webhook_secret_enc
  FROM hub.repositories WHERE id = @id AND provider = @provider;

-- build_id — derived: Сборка первой подписки (deprecated wire-поле, тикет 011);
-- LEFT JOIN на таблицу (не derived) — так sqlc выводит nullable *int64.
-- name: Repositories :many
SELECT r.id, r.user_id, r.identity_id, r.mode, r.provider, r.external_id, r.owner, r.name,
       r.default_branch, r.webhook_provider_id, r.webhook_secret_enc, bs.build_id, r.connected_at
  FROM hub.repositories r
  LEFT JOIN hub.build_subscriptions bs
         ON bs.id = (SELECT min(id) FROM hub.build_subscriptions WHERE repository_id = r.id)
 WHERE r.user_id = @user_id ORDER BY r.id;

-- name: Repository :one
SELECT r.id, r.user_id, r.identity_id, r.mode, r.provider, r.external_id, r.owner, r.name,
       r.default_branch, r.webhook_provider_id, r.webhook_secret_enc, bs.build_id, r.connected_at
  FROM hub.repositories r
  LEFT JOIN hub.build_subscriptions bs
         ON bs.id = (SELECT min(id) FROM hub.build_subscriptions WHERE repository_id = r.id)
 WHERE r.id = @id AND r.user_id = @user_id;

-- name: CreateRepository :one
INSERT INTO hub.repositories
  (user_id, identity_id, mode, provider, external_id, owner, name, default_branch, webhook_secret_enc)
VALUES (@user_id, @identity_id, @mode, @provider, @external_id, @owner, @name, @default_branch, @webhook_secret_enc)
RETURNING id;

-- name: SetWebhook :exec
UPDATE hub.repositories SET webhook_provider_id = @webhook_provider_id WHERE id = @id;

-- name: DeleteRepository :exec
DELETE FROM hub.repositories WHERE id = @id;

-- name: Events :many
SELECT id, provider, action, commit_sha, ref, received_at, trace_id
  FROM hub.events WHERE repository_id = @repository_id ORDER BY id DESC LIMIT @row_limit::int;

-- name: SubscriptionsByRepo :many
SELECT id, build_id, repository_id, actions, ref_mask, created_at
  FROM hub.build_subscriptions WHERE repository_id = @repository_id ORDER BY id;

-- name: UpsertSubscription :one
INSERT INTO hub.build_subscriptions (build_id, repository_id, actions, ref_mask)
VALUES (@build_id, @repository_id, COALESCE(@actions::text[], '{}'::text[]), @ref_mask)
ON CONFLICT (build_id, repository_id) DO UPDATE
  SET actions = COALESCE(@actions::text[], '{}'::text[]), ref_mask = @ref_mask
RETURNING id;

-- name: DeleteSubscription :execrows
DELETE FROM hub.build_subscriptions bs
 USING hub.repositories r
 WHERE bs.id = @id AND r.id = bs.repository_id AND r.user_id = @user_id;

-- name: DefaultBuild :one
SELECT id, user_id, name FROM hub.agent_builds
 WHERE user_id = @user_id AND is_default ORDER BY id LIMIT 1;
