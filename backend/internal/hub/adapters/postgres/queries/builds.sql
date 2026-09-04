-- Сборки Агента и Подключения

-- name: Builds :many
SELECT id, user_id, name, llm_connection_id, sandbox_connection_id,
       prompt, memory_preset, limits, created_at
  FROM hub.agent_builds WHERE user_id = @user_id ORDER BY id;

-- name: Build :one
SELECT id, user_id, name, llm_connection_id, sandbox_connection_id,
       prompt, memory_preset, limits, created_at
  FROM hub.agent_builds WHERE id = @id;

-- name: CreateBuild :one
INSERT INTO hub.agent_builds
  (user_id, name, llm_connection_id, sandbox_connection_id, prompt, memory_preset, limits)
VALUES (@user_id, @name, @llm_connection_id, @sandbox_connection_id, @prompt, @memory_preset,
        COALESCE(@limits::jsonb, '{}'::jsonb))
RETURNING id;

-- name: UpdateBuild :execrows
UPDATE hub.agent_builds
   SET name = @name, llm_connection_id = @llm_connection_id, sandbox_connection_id = @sandbox_connection_id,
       prompt = @prompt, memory_preset = @memory_preset,
       limits = COALESCE(@limits::jsonb, '{}'::jsonb)
 WHERE id = @id AND user_id = @user_id;

-- name: DeleteBuild :execrows
DELETE FROM hub.agent_builds WHERE id = @id AND user_id = @user_id;

-- name: LlmConnections :many
SELECT id, user_id, name, api_base, api_key_enc, model, created_at, params
  FROM hub.llm_connections WHERE user_id = @user_id ORDER BY id;

-- name: LlmConnection :one
SELECT id, user_id, name, api_base, api_key_enc, model, created_at, params
  FROM hub.llm_connections WHERE id = @id AND user_id = @user_id;

-- name: CreateLlmConnection :one
INSERT INTO hub.llm_connections (user_id, name, api_base, api_key_enc, model, params)
VALUES (@user_id, @name, @api_base, @api_key_enc, @model, COALESCE(@params::jsonb, '{}'::jsonb)) RETURNING id;

-- Ключ меняется только если передан (NULL — оставить прежний).
-- name: UpdateLlmConnection :execrows
UPDATE hub.llm_connections
   SET name = @name, api_base = @api_base, model = @model,
       params = COALESCE(@params::jsonb, '{}'::jsonb),
       api_key_enc = COALESCE(sqlc.narg('api_key_enc')::bytea, api_key_enc)
 WHERE id = @id AND user_id = @user_id;

-- name: DeleteLlmConnection :execrows
DELETE FROM hub.llm_connections WHERE id = @id AND user_id = @user_id;

-- name: SandboxConnections :many
SELECT id, name, domain, api_key_enc, image, created_at FROM hub.sandbox_connections ORDER BY id;

-- name: SandboxConnection :one
SELECT id, name, domain, api_key_enc, image, created_at FROM hub.sandbox_connections WHERE id = @id;

-- name: CreateSandboxConnection :one
INSERT INTO hub.sandbox_connections (name, domain, api_key_enc, image)
VALUES (@name, @domain, @api_key_enc, @image) RETURNING id;

-- name: DeleteSandboxConnection :execrows
DELETE FROM hub.sandbox_connections WHERE id = @id;
