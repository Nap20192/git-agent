package postgres

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

var (
	_ domain.IdentityStore   = (*Store)(nil)
	_ domain.RepositoryAdmin = (*Store)(nil)
	_ domain.BuildStore      = (*Store)(nil)
	_ domain.ConnectionStore = (*Store)(nil)
	_ domain.InstanceStore   = (*Store)(nil)
	_ domain.StaleRequeuer   = (*Store)(nil)
)

func nilIfNoRows[T any](v *T, err error) (*T, error) {
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return v, nil
}

// isFKViolation — код 23503 (нарушение внешнего ключа).
func isFKViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23503"
}

// EnsureDevUser — первый пользователь БД (создаётся при пустой таблице).
// TODO(auth, тикет 003): убрать вместе с dev-пропуском Session после OAuth-входа.
func (s *Store) EnsureDevUser(ctx context.Context) (int64, error) {
	var id int64
	err := s.Pool.QueryRow(ctx, `SELECT id FROM hub.users ORDER BY id LIMIT 1`).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		err = s.Pool.QueryRow(ctx, `INSERT INTO hub.users (display_name) VALUES ('dev') RETURNING id`).Scan(&id)
	}
	return id, err
}

// ── Identities ──────────────────────────────────────────────────────────────

func (s *Store) Identities(ctx context.Context, userID int64) ([]domain.Identity, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT id, user_id, provider, username, access_token_enc, created_at
		   FROM hub.identities WHERE user_id = $1 ORDER BY id`, userID)
	if err != nil {
		return nil, err
	}
	return collect(rows, scanIdentity)
}

func (s *Store) Identity(ctx context.Context, id, userID int64) (*domain.Identity, error) {
	row := s.Pool.QueryRow(ctx,
		`SELECT id, user_id, provider, username, access_token_enc, created_at
		   FROM hub.identities WHERE id = $1 AND user_id = $2`, id, userID)
	i, err := scanIdentityRow(row)
	return nilIfNoRows(&i, err)
}

func (s *Store) DeleteIdentity(ctx context.Context, id, userID int64) error {
	tag, err := s.Pool.Exec(ctx,
		`DELETE FROM hub.identities WHERE id = $1 AND user_id = $2`, id, userID)
	if isFKViolation(err) {
		return domain.ErrConflict
	}
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return domain.ErrNotFound
	}
	return nil
}

// ── Repositories ────────────────────────────────────────────────────────────

const repoColumns = `id, user_id, identity_id, provider, external_id, owner, name,
	default_branch, webhook_provider_id, webhook_secret_enc, build_id, connected_at`

func (s *Store) Repositories(ctx context.Context, userID int64) ([]domain.Repository, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT `+repoColumns+` FROM hub.repositories WHERE user_id = $1 ORDER BY id`, userID)
	if err != nil {
		return nil, err
	}
	return collect(rows, scanRepository)
}

func (s *Store) Repository(ctx context.Context, id, userID int64) (*domain.Repository, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT `+repoColumns+` FROM hub.repositories WHERE id = $1 AND user_id = $2`, id, userID)
	if err != nil {
		return nil, err
	}
	list, err := collect(rows, scanRepository)
	if err != nil || len(list) == 0 {
		return nil, err
	}
	return &list[0], nil
}

func (s *Store) CreateRepository(ctx context.Context, r *domain.Repository) (int64, error) {
	var id int64
	err := s.Pool.QueryRow(ctx,
		`INSERT INTO hub.repositories
		   (user_id, identity_id, provider, external_id, owner, name, default_branch, webhook_secret_enc, build_id)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id`,
		r.UserID, r.IdentityID, r.Provider, r.ExternalID, r.Owner, r.Name,
		r.DefaultBranch, r.WebhookSecretEnc, r.BuildID,
	).Scan(&id)
	return id, err
}

func (s *Store) SetWebhook(ctx context.Context, id int64, providerHookID string) error {
	_, err := s.Pool.Exec(ctx,
		`UPDATE hub.repositories SET webhook_provider_id = $2 WHERE id = $1`, id, providerHookID)
	return err
}

func (s *Store) SetBuild(ctx context.Context, id, userID int64, buildID *int64) error {
	tag, err := s.Pool.Exec(ctx,
		`UPDATE hub.repositories SET build_id = $3 WHERE id = $1 AND user_id = $2`, id, userID, buildID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return domain.ErrNotFound
	}
	return nil
}

func (s *Store) DeleteRepository(ctx context.Context, id int64) error {
	_, err := s.Pool.Exec(ctx, `DELETE FROM hub.repositories WHERE id = $1`, id)
	return err
}

func (s *Store) Events(ctx context.Context, repoID int64, limit int) ([]domain.EventRecord, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT id, provider, action, commit_sha, ref, received_at
		   FROM hub.events WHERE repository_id = $1 ORDER BY id DESC LIMIT $2`, repoID, limit)
	if err != nil {
		return nil, err
	}
	return collect(rows, func(r pgx.Rows) (domain.EventRecord, error) {
		var e domain.EventRecord
		err := r.Scan(&e.ID, &e.Provider, &e.Action, &e.CommitSHA, &e.Ref, &e.ReceivedAt)
		return e, err
	})
}

// ── Builds ──────────────────────────────────────────────────────────────────

func (s *Store) Builds(ctx context.Context, userID int64) ([]domain.AgentBuild, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT id, user_id, name, llm_connection_id, sandbox_connection_id,
		        prompt, memory_preset, limits, is_default, created_at
		   FROM hub.agent_builds WHERE user_id = $1 ORDER BY id`, userID)
	if err != nil {
		return nil, err
	}
	return collect(rows, func(r pgx.Rows) (domain.AgentBuild, error) {
		var b domain.AgentBuild
		err := r.Scan(&b.ID, &b.UserID, &b.Name, &b.LlmConnectionID, &b.SandboxConnectionID,
			&b.Prompt, &b.MemoryPreset, &b.Limits, &b.IsDefault, &b.CreatedAt)
		return b, err
	})
}

func (s *Store) CreateBuild(ctx context.Context, b *domain.AgentBuild) (int64, error) {
	var id int64
	err := s.Pool.QueryRow(ctx,
		`INSERT INTO hub.agent_builds
		   (user_id, name, llm_connection_id, sandbox_connection_id, prompt, memory_preset, limits, is_default)
		 VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, '{}'::jsonb), $8) RETURNING id`,
		b.UserID, b.Name, b.LlmConnectionID, b.SandboxConnectionID,
		b.Prompt, b.MemoryPreset, b.Limits, b.IsDefault,
	).Scan(&id)
	if isFKViolation(err) {
		return 0, domain.ErrConflict
	}
	return id, err
}

func (s *Store) UpdateBuild(ctx context.Context, b *domain.AgentBuild) error {
	tag, err := s.Pool.Exec(ctx,
		`UPDATE hub.agent_builds
		    SET name = $3, llm_connection_id = $4, sandbox_connection_id = $5,
		        prompt = $6, memory_preset = $7, limits = COALESCE($8, '{}'::jsonb), is_default = $9
		  WHERE id = $1 AND user_id = $2`,
		b.ID, b.UserID, b.Name, b.LlmConnectionID, b.SandboxConnectionID,
		b.Prompt, b.MemoryPreset, b.Limits, b.IsDefault)
	if isFKViolation(err) {
		return domain.ErrConflict
	}
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return domain.ErrNotFound
	}
	return nil
}

func (s *Store) DeleteBuild(ctx context.Context, id, userID int64) error {
	tag, err := s.Pool.Exec(ctx,
		`DELETE FROM hub.agent_builds WHERE id = $1 AND user_id = $2`, id, userID)
	if isFKViolation(err) {
		return domain.ErrConflict
	}
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return domain.ErrNotFound
	}
	return nil
}

// ── Connections ─────────────────────────────────────────────────────────────

func (s *Store) LlmConnections(ctx context.Context, userID int64) ([]domain.LlmConnection, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT id, user_id, name, api_base, api_key_enc, model, created_at
		   FROM hub.llm_connections WHERE user_id = $1 ORDER BY id`, userID)
	if err != nil {
		return nil, err
	}
	return collect(rows, func(r pgx.Rows) (domain.LlmConnection, error) {
		var c domain.LlmConnection
		err := r.Scan(&c.ID, &c.UserID, &c.Name, &c.APIBase, &c.APIKeyEnc, &c.Model, &c.CreatedAt)
		return c, err
	})
}

func (s *Store) CreateLlmConnection(ctx context.Context, c *domain.LlmConnection) (int64, error) {
	var id int64
	err := s.Pool.QueryRow(ctx,
		`INSERT INTO hub.llm_connections (user_id, name, api_base, api_key_enc, model)
		 VALUES ($1, $2, $3, $4, $5) RETURNING id`,
		c.UserID, c.Name, c.APIBase, c.APIKeyEnc, c.Model,
	).Scan(&id)
	return id, err
}

func (s *Store) DeleteLlmConnection(ctx context.Context, id, userID int64) error {
	tag, err := s.Pool.Exec(ctx,
		`DELETE FROM hub.llm_connections WHERE id = $1 AND user_id = $2`, id, userID)
	if isFKViolation(err) {
		return domain.ErrConflict
	}
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return domain.ErrNotFound
	}
	return nil
}

func (s *Store) SandboxConnections(ctx context.Context) ([]domain.SandboxConnection, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT id, name, domain, api_key_enc, image, created_at
		   FROM hub.sandbox_connections ORDER BY id`)
	if err != nil {
		return nil, err
	}
	return collect(rows, func(r pgx.Rows) (domain.SandboxConnection, error) {
		var c domain.SandboxConnection
		err := r.Scan(&c.ID, &c.Name, &c.Domain, &c.APIKeyEnc, &c.Image, &c.CreatedAt)
		return c, err
	})
}

func (s *Store) CreateSandboxConnection(ctx context.Context, c *domain.SandboxConnection) (int64, error) {
	var id int64
	err := s.Pool.QueryRow(ctx,
		`INSERT INTO hub.sandbox_connections (name, domain, api_key_enc, image)
		 VALUES ($1, $2, $3, $4) RETURNING id`,
		c.Name, c.Domain, c.APIKeyEnc, c.Image,
	).Scan(&id)
	return id, err
}

func (s *Store) DeleteSandboxConnection(ctx context.Context, id int64) error {
	tag, err := s.Pool.Exec(ctx, `DELETE FROM hub.sandbox_connections WHERE id = $1`, id)
	if isFKViolation(err) {
		return domain.ErrConflict
	}
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return domain.ErrNotFound
	}
	return nil
}

// ── Instances ───────────────────────────────────────────────────────────────

const instanceColumns = `i.id, i.build_id, i.repository_id, i.sandbox_instance_id,
	i.thread_id, i.status, i.runner_id, i.updated_at`

func (s *Store) Instances(ctx context.Context, userID int64, repositoryID *int64) ([]domain.AgentInstance, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT `+instanceColumns+`
		   FROM hub.agent_instances i JOIN hub.repositories r ON r.id = i.repository_id
		  WHERE r.user_id = $1 AND ($2::bigint IS NULL OR i.repository_id = $2)
		  ORDER BY i.id`, userID, repositoryID)
	if err != nil {
		return nil, err
	}
	return collect(rows, scanInstance)
}

func (s *Store) Instance(ctx context.Context, id, userID int64) (*domain.AgentInstance, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT `+instanceColumns+`
		   FROM hub.agent_instances i JOIN hub.repositories r ON r.id = i.repository_id
		  WHERE i.id = $1 AND r.user_id = $2`, id, userID)
	if err != nil {
		return nil, err
	}
	list, err := collect(rows, scanInstance)
	if err != nil || len(list) == 0 {
		return nil, err
	}
	return &list[0], nil
}

func (s *Store) Reports(ctx context.Context, instanceID int64) ([]domain.Report, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT id, instance_id, event_id, summary, created_at
		   FROM hub.reports WHERE instance_id = $1 ORDER BY id DESC`, instanceID)
	if err != nil {
		return nil, err
	}
	return collect(rows, func(r pgx.Rows) (domain.Report, error) {
		var rep domain.Report
		err := r.Scan(&rep.ID, &rep.InstanceID, &rep.EventID, &rep.Summary, &rep.CreatedAt)
		return rep, err
	})
}

func (s *Store) Findings(ctx context.Context, instanceID int64) ([]domain.Finding, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT id, instance_id, report_id, severity, cwe, cve, file, line_start, line_end,
		        evidence, remediation, created_at
		   FROM hub.findings WHERE instance_id = $1 ORDER BY id DESC`, instanceID)
	if err != nil {
		return nil, err
	}
	return collect(rows, func(r pgx.Rows) (domain.Finding, error) {
		var f domain.Finding
		err := r.Scan(&f.ID, &f.InstanceID, &f.ReportID, &f.Severity, &f.CWE, &f.CVE,
			&f.File, &f.LineStart, &f.LineEnd, &f.Evidence, &f.Remediation, &f.CreatedAt)
		return f, err
	})
}

func (s *Store) SetInstanceRunning(ctx context.Context, id, runnerID int64) error {
	_, err := s.Pool.Exec(ctx,
		`UPDATE hub.agent_instances
		    SET status = 'running', runner_id = $2, updated_at = now() WHERE id = $1`, id, runnerID)
	return err
}

func (s *Store) SetInstanceDown(ctx context.Context, id int64) error {
	_, err := s.Pool.Exec(ctx,
		`UPDATE hub.agent_instances
		    SET status = 'down', runner_id = NULL, updated_at = now() WHERE id = $1`, id)
	return err
}

// ── Runners (расширение) и надзор за heartbeat ─────────────────────────────

func (s *Store) Runners(ctx context.Context) ([]domain.Runner, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT id, name, address, slots, last_heartbeat_at FROM hub.runners ORDER BY id`)
	if err != nil {
		return nil, err
	}
	return collect(rows, scanRunner)
}

func (s *Store) Runner(ctx context.Context, id int64) (*domain.Runner, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT id, name, address, slots, last_heartbeat_at FROM hub.runners WHERE id = $1`, id)
	if err != nil {
		return nil, err
	}
	list, err := collect(rows, scanRunner)
	if err != nil || len(list) == 0 {
		return nil, err
	}
	return &list[0], nil
}

func (s *Store) FreeRunner(ctx context.Context, aliveWithin time.Duration) (*domain.Runner, error) {
	rows, err := s.Pool.Query(ctx,
		`SELECT r.id, r.name, r.address, r.slots, r.last_heartbeat_at
		   FROM hub.runners r
		  WHERE r.last_heartbeat_at > now() - $1::interval
		    AND r.slots > (SELECT count(*) FROM hub.agent_instances i
		                    WHERE i.runner_id = r.id AND i.status = 'running')
		  ORDER BY r.last_heartbeat_at DESC LIMIT 1`, aliveWithin)
	if err != nil {
		return nil, err
	}
	list, err := collect(rows, scanRunner)
	if err != nil || len(list) == 0 {
		return nil, err
	}
	return &list[0], nil
}

// RequeueStale — один SQL-стейтмент: running-Экземпляры протухших Раннеров →
// down, их необработанные События (instance_events без processed_at) — новыми
// строками outbox (routing_key/payload копируются из исходной публикации).
func (s *Store) RequeueStale(ctx context.Context, timeout time.Duration) (int, int, error) {
	var downed, requeued int
	err := s.Pool.QueryRow(ctx, `
		WITH downed AS (
			UPDATE hub.agent_instances SET status = 'down', runner_id = NULL, updated_at = now()
			 WHERE status = 'running'
			   AND runner_id IN (SELECT id FROM hub.runners WHERE last_heartbeat_at < now() - $1::interval)
			 RETURNING id
		), requeued AS (
			INSERT INTO hub.outbox (event_id, routing_key, payload)
			SELECT ie.event_id, o.routing_key, o.payload
			  FROM hub.instance_events ie
			  JOIN downed d ON d.id = ie.instance_id
			  JOIN LATERAL (SELECT routing_key, payload FROM hub.outbox o2
			                 WHERE o2.event_id = ie.event_id ORDER BY o2.id LIMIT 1) o ON true
			 WHERE ie.processed_at IS NULL
			 RETURNING id
		)
		SELECT (SELECT count(*) FROM downed), (SELECT count(*) FROM requeued)`,
		timeout,
	).Scan(&downed, &requeued)
	return downed, requeued, err
}

// ── скан-хелперы ────────────────────────────────────────────────────────────

func collect[T any](rows pgx.Rows, scan func(pgx.Rows) (T, error)) ([]T, error) {
	defer rows.Close()
	var out []T
	for rows.Next() {
		v, err := scan(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func scanIdentity(r pgx.Rows) (domain.Identity, error) {
	var i domain.Identity
	err := r.Scan(&i.ID, &i.UserID, &i.Provider, &i.Username, &i.AccessTokenEnc, &i.CreatedAt)
	return i, err
}

func scanIdentityRow(row pgx.Row) (domain.Identity, error) {
	var i domain.Identity
	err := row.Scan(&i.ID, &i.UserID, &i.Provider, &i.Username, &i.AccessTokenEnc, &i.CreatedAt)
	return i, err
}

func scanRepository(r pgx.Rows) (domain.Repository, error) {
	var repo domain.Repository
	err := r.Scan(&repo.ID, &repo.UserID, &repo.IdentityID, &repo.Provider, &repo.ExternalID,
		&repo.Owner, &repo.Name, &repo.DefaultBranch, &repo.WebhookProviderID,
		&repo.WebhookSecretEnc, &repo.BuildID, &repo.ConnectedAt)
	return repo, err
}

func scanInstance(r pgx.Rows) (domain.AgentInstance, error) {
	var i domain.AgentInstance
	err := r.Scan(&i.ID, &i.BuildID, &i.RepositoryID, &i.SandboxInstanceID,
		&i.ThreadID, &i.Status, &i.RunnerID, &i.UpdatedAt)
	return i, err
}

func scanRunner(r pgx.Rows) (domain.Runner, error) {
	var run domain.Runner
	err := r.Scan(&run.ID, &run.Name, &run.Address, &run.Slots, &run.LastHeartbeatAt)
	return run, err
}
