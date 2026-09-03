-- Auth: пользователи, сессии, OAuth-связки (тикет 003)

-- name: CreateUser :one
INSERT INTO hub.users (display_name) VALUES (@display_name) RETURNING id;

-- name: UserDisplayName :one
SELECT display_name FROM hub.users WHERE id = @id;

-- name: FindIdentityByProviderUser :one
SELECT id, user_id, provider, provider_user_id, username,
       access_token_enc, refresh_token_enc, token_expires_at, created_at
  FROM hub.identities
 WHERE provider = @provider AND provider_user_id = @provider_user_id;

-- name: InsertIdentity :one
INSERT INTO hub.identities
  (user_id, provider, provider_user_id, username, access_token_enc, refresh_token_enc, token_expires_at)
VALUES (@user_id, @provider, @provider_user_id, @username, @access_token_enc, @refresh_token_enc, @token_expires_at)
RETURNING id;

-- name: UpdateIdentityTokens :exec
UPDATE hub.identities
   SET username = @username, access_token_enc = @access_token_enc,
       refresh_token_enc = COALESCE(@refresh_token_enc::bytea, refresh_token_enc),
       token_expires_at = @token_expires_at
 WHERE id = @id;

-- name: CreateSession :exec
INSERT INTO hub.sessions (token, user_id, expires_at) VALUES (@token, @user_id, @expires_at);

-- name: SessionUser :one
SELECT user_id FROM hub.sessions WHERE token = @token AND expires_at > now();

-- name: DeleteSession :exec
DELETE FROM hub.sessions WHERE token = @token;

-- name: Identities :many
SELECT id, user_id, provider, provider_user_id, username,
       access_token_enc, refresh_token_enc, token_expires_at, created_at
  FROM hub.identities WHERE user_id = @user_id ORDER BY id;

-- name: Identity :one
SELECT id, user_id, provider, provider_user_id, username,
       access_token_enc, refresh_token_enc, token_expires_at, created_at
  FROM hub.identities WHERE id = @id AND user_id = @user_id;

-- name: DeleteIdentity :execrows
DELETE FROM hub.identities WHERE id = @id AND user_id = @user_id;
