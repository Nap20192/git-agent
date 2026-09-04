// Package postgres — outbound-адаптер хранения: реализация доменных портов
// hub поверх pgx-пула (схема hub.*, migrations/backend/). SQL — в queries/*.sql,
// типизированный код генерирует sqlc (task backend:sqlc) в пакет db; здесь —
// только маппинг строк в domain-типы (приведением: поля совпадают по имени
// и типу, см. rename/overrides в sqlc.yaml) и перевод ошибок в domain.Err*.
package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres/db"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

type Store struct {
	Pool *pgxpool.Pool
}

var (
	_ domain.RepositoryStore      = (*Store)(nil)
	_ domain.EventIngestor        = (*Store)(nil)
	_ domain.OutboxStore          = (*Store)(nil)
	_ domain.RunnerStore          = (*Store)(nil)
	_ domain.IdentityStore        = (*Store)(nil)
	_ domain.RepositoryAdmin      = (*Store)(nil)
	_ domain.BuildStore           = (*Store)(nil)
	_ domain.ConnectionStore      = (*Store)(nil)
	_ domain.InstanceStore        = (*Store)(nil)
	_ domain.SandboxInstanceStore = (*Store)(nil)
	_ domain.StaleRequeuer        = (*Store)(nil)
	_ domain.SubscriptionStore    = (*Store)(nil)
	_ domain.AuthStore            = (*Store)(nil)
)

func (s *Store) q() *db.Queries { return db.New(s.Pool) }

// ── хелперы перевода ошибок ─────────────────────────────────────────────────

// isFKViolation — код 23503 (нарушение внешнего ключа).
func isFKViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23503"
}

// optional — :one без строки = nil, nil (не ошибка).
func optional[T any](v T, err error) (*T, error) {
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &v, nil
}

// conflictOnFK — FK-нарушение = domain.ErrConflict (сущность в использовании / ссылка на чужое).
func conflictOnFK[T any](v T, err error) (T, error) {
	if isFKViolation(err) {
		return v, domain.ErrConflict
	}
	return v, err
}

// affected — :execrows: FK → ErrConflict, ноль строк → ErrNotFound.
func affected(n int64, err error) error {
	if isFKViolation(err) {
		return domain.ErrConflict
	}
	if err != nil {
		return err
	}
	if n == 0 {
		return domain.ErrNotFound
	}
	return nil
}

func mapRows[T, U any](rows []T, err error, conv func(T) U) ([]U, error) {
	if err != nil {
		return nil, err
	}
	out := make([]U, len(rows))
	for i, r := range rows {
		out[i] = conv(r)
	}
	return out, nil
}

// ── Webhook ingest / outbox ─────────────────────────────────────────────────

func (s *Store) Find(ctx context.Context, id int64, provider string) (*domain.Repository, error) {
	r, err := optional(s.q().FindRepository(ctx, db.FindRepositoryParams{ID: id, Provider: provider}))
	if r == nil || err != nil {
		return nil, err
	}
	return &domain.Repository{ID: id, Provider: provider, UserID: r.UserID, Owner: r.Owner, Name: r.Name,
		WebhookSecretEnc: r.WebhookSecretEnc}, nil
}

// Ingest — одна транзакция: журнал hub.events (дедуп по provider+delivery_id)
// + веер (тикет 011): upsert Экземпляра каждой Сборки из buildIDs, журнал
// instance_events, строка outbox на каждый Экземпляр (контракт тикета 010 —
// в сообщении готовые instanceId/threadId). Ноль Сборок — только журнал.
func (s *Store) Ingest(ctx context.Context, repo *domain.Repository, e domain.Event, payload []byte, buildIDs []int64) (bool, []int64, error) {
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return false, nil, err
	}
	defer tx.Rollback(ctx)
	q := s.q().WithTx(tx)

	eventID, err := q.InsertEvent(ctx, db.InsertEventParams{
		Provider: repo.Provider, DeliveryID: e.DeliveryID, RepositoryID: repo.ID,
		Action: e.Action, CommitSHA: e.CommitSHA, Ref: e.Ref, Payload: payload, TraceID: e.TraceID,
		BeforeSHA: e.BeforeSHA, BaseSHA: e.BaseSHA, HeadSHA: e.HeadSHA,
		PRNumber: e.PRNumber, PRTitle: e.PRTitle, PRBody: e.PRBody, ChangedFiles: changedFilesJSON(e.ChangedFiles),
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return true, nil, nil
	}
	if err != nil {
		return false, nil, fmt.Errorf("insert event: %w", err)
	}

	var instanceIDs []int64
	routingKey := domain.RoutingKey(repo.Provider, repo.ID, e.Action)
	for _, buildID := range buildIDs {
		inst, err := q.UpsertInstance(ctx, db.UpsertInstanceParams{
			BuildID: buildID, RepositoryID: repo.ID, ThreadID: threadID(buildID, repo.ID),
		})
		if err != nil {
			return false, nil, fmt.Errorf("upsert instance (build %d): %w", buildID, err)
		}
		if err := q.InsertInstanceEvent(ctx, db.InsertInstanceEventParams{
			InstanceID: inst.ID, EventID: eventID, DedupKey: domain.DedupKey(eventID, e),
		}); err != nil {
			return false, nil, fmt.Errorf("insert instance event: %w", err)
		}
		if err := q.InsertOutbox(ctx, db.InsertOutboxParams{
			EventID: eventID, RoutingKey: routingKey,
			Payload: domain.EventMessage(eventID, inst.ID, inst.ThreadID, repo, e),
		}); err != nil {
			return false, nil, fmt.Errorf("insert outbox: %w", err)
		}
		instanceIDs = append(instanceIDs, inst.ID)
	}
	return false, instanceIDs, tx.Commit(ctx)
}

// changedFilesJSON — JSON-массив для jsonb; nil при пустом списке → NULL.
func changedFilesJSON(files []string) json.RawMessage {
	if len(files) == 0 {
		return nil
	}
	b, _ := json.Marshal(files)
	return b
}

func (s *Store) Unpublished(ctx context.Context, limit int) ([]domain.OutboxMessage, error) {
	rows, err := s.q().Unpublished(ctx, limit)
	return mapRows(rows, err, func(r db.UnpublishedRow) domain.OutboxMessage { return domain.OutboxMessage(r) })
}

func (s *Store) MarkPublished(ctx context.Context, id int64) error {
	return s.q().MarkPublished(ctx, id)
}

// ── Auth: пользователи и сессии (тикет 003) ─────────────────────────────────

func (s *Store) CreateUser(ctx context.Context, displayName string) (int64, error) {
	return s.q().CreateUser(ctx, displayName)
}

func (s *Store) UserDisplayName(ctx context.Context, id int64) (string, error) {
	name, err := s.q().UserDisplayName(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", domain.ErrNotFound
	}
	return name, err
}

func (s *Store) FindIdentityByProviderUser(ctx context.Context, provider, providerUserID string) (*domain.Identity, error) {
	i, err := optional(s.q().FindIdentityByProviderUser(ctx, db.FindIdentityByProviderUserParams{Provider: provider, ProviderUserID: providerUserID}))
	if i == nil || err != nil {
		return nil, err
	}
	return (*domain.Identity)(i), nil
}

func (s *Store) InsertIdentity(ctx context.Context, i *domain.Identity) (int64, error) {
	return s.q().InsertIdentity(ctx, db.InsertIdentityParams{
		UserID: i.UserID, Provider: i.Provider, ProviderUserID: i.ProviderUserID, Username: i.Username,
		AccessTokenEnc: i.AccessTokenEnc, RefreshTokenEnc: i.RefreshTokenEnc, TokenExpiresAt: i.TokenExpiresAt,
	})
}

func (s *Store) UpdateIdentityTokens(ctx context.Context, id int64, username string, accessEnc, refreshEnc []byte, expiresAt *time.Time) error {
	return s.q().UpdateIdentityTokens(ctx, db.UpdateIdentityTokensParams{
		ID: id, Username: username, AccessTokenEnc: accessEnc, RefreshTokenEnc: refreshEnc, TokenExpiresAt: expiresAt,
	})
}

func (s *Store) CreateSession(ctx context.Context, token string, userID int64, expiresAt time.Time) error {
	return s.q().CreateSession(ctx, db.CreateSessionParams{Token: token, UserID: userID, ExpiresAt: expiresAt})
}

func (s *Store) SessionUser(ctx context.Context, token string) (int64, bool, error) {
	userID, err := s.q().SessionUser(ctx, token)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, false, nil
	}
	return userID, err == nil, err
}

func (s *Store) DeleteSession(ctx context.Context, token string) error {
	return s.q().DeleteSession(ctx, token)
}

// ── Identities ──────────────────────────────────────────────────────────────

func (s *Store) Identities(ctx context.Context, userID int64) ([]domain.Identity, error) {
	rows, err := s.q().Identities(ctx, userID)
	return mapRows(rows, err, func(r db.HubIdentity) domain.Identity { return domain.Identity(r) })
}

func (s *Store) Identity(ctx context.Context, id, userID int64) (*domain.Identity, error) {
	i, err := optional(s.q().Identity(ctx, db.IdentityParams{ID: id, UserID: userID}))
	if i == nil || err != nil {
		return nil, err
	}
	return (*domain.Identity)(i), nil
}

func (s *Store) DeleteIdentity(ctx context.Context, id, userID int64) error {
	return affected(s.q().DeleteIdentity(ctx, db.DeleteIdentityParams{ID: id, UserID: userID}))
}

// ── Repositories ────────────────────────────────────────────────────────────

func (s *Store) Repositories(ctx context.Context, userID int64) ([]domain.Repository, error) {
	rows, err := s.q().Repositories(ctx, userID)
	return mapRows(rows, err, func(r db.RepositoriesRow) domain.Repository { return domain.Repository(r) })
}

func (s *Store) Repository(ctx context.Context, id, userID int64) (*domain.Repository, error) {
	r, err := optional(s.q().Repository(ctx, db.RepositoryParams{ID: id, UserID: userID}))
	if r == nil || err != nil {
		return nil, err
	}
	return (*domain.Repository)(r), nil
}

func (s *Store) CreateRepository(ctx context.Context, r *domain.Repository) (int64, error) {
	return s.q().CreateRepository(ctx, db.CreateRepositoryParams{
		UserID: r.UserID, IdentityID: r.IdentityID, Mode: r.Mode, Provider: r.Provider, ExternalID: r.ExternalID,
		Owner: r.Owner, Name: r.Name, DefaultBranch: r.DefaultBranch, WebhookSecretEnc: r.WebhookSecretEnc,
	})
}

func (s *Store) SetWebhook(ctx context.Context, id int64, providerHookID string) error {
	return s.q().SetWebhook(ctx, db.SetWebhookParams{ID: id, WebhookProviderID: &providerHookID})
}

func (s *Store) DeleteRepository(ctx context.Context, id int64) error {
	return s.q().DeleteRepository(ctx, id)
}

func (s *Store) Events(ctx context.Context, repoID int64, limit int) ([]domain.EventRecord, error) {
	rows, err := s.q().Events(ctx, db.EventsParams{RepositoryID: repoID, RowLimit: limit})
	return mapRows(rows, err, func(r db.EventsRow) domain.EventRecord { return domain.EventRecord(r) })
}

func (s *Store) LastProcessedCommit(ctx context.Context, repoID int64) (string, error) {
	sha, err := s.q().LastProcessedCommit(ctx, repoID)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	return sha, err
}

// ── Subscriptions (тикет 011) ───────────────────────────────────────────────

func (s *Store) SubscriptionsByRepo(ctx context.Context, repositoryID int64) ([]domain.BuildSubscription, error) {
	rows, err := s.q().SubscriptionsByRepo(ctx, repositoryID)
	return mapRows(rows, err, func(r db.HubBuildSubscription) domain.BuildSubscription { return domain.BuildSubscription(r) })
}

func (s *Store) UpsertSubscription(ctx context.Context, sub *domain.BuildSubscription) (int64, error) {
	return conflictOnFK(s.q().UpsertSubscription(ctx, db.UpsertSubscriptionParams{
		BuildID: sub.BuildID, RepositoryID: sub.RepositoryID, Actions: sub.Actions, RefMask: sub.RefMask,
	}))
}

func (s *Store) DeleteSubscription(ctx context.Context, id, userID int64) error {
	return affected(s.q().DeleteSubscription(ctx, db.DeleteSubscriptionParams{ID: id, UserID: userID}))
}

func (s *Store) DefaultBuild(ctx context.Context, userID int64) (*domain.AgentBuild, error) {
	b, err := optional(s.q().DefaultBuild(ctx, userID))
	if b == nil || err != nil {
		return nil, err
	}
	return &domain.AgentBuild{ID: b.ID, UserID: b.UserID, Name: b.Name}, nil
}

// ── Builds ──────────────────────────────────────────────────────────────────

func (s *Store) Build(ctx context.Context, id int64) (*domain.AgentBuild, error) {
	b, err := optional(s.q().Build(ctx, id))
	if b == nil || err != nil {
		return nil, err
	}
	return (*domain.AgentBuild)(b), nil
}

func (s *Store) Builds(ctx context.Context, userID int64) ([]domain.AgentBuild, error) {
	rows, err := s.q().Builds(ctx, userID)
	return mapRows(rows, err, func(r db.HubAgentBuild) domain.AgentBuild { return domain.AgentBuild(r) })
}

func (s *Store) CreateBuild(ctx context.Context, b *domain.AgentBuild) (int64, error) {
	return conflictOnFK(s.q().CreateBuild(ctx, db.CreateBuildParams{
		UserID: b.UserID, Name: b.Name, LlmConnectionID: b.LlmConnectionID, SandboxConnectionID: b.SandboxConnectionID,
		Prompt: b.Prompt, MemoryPreset: b.MemoryPreset, Limits: b.Limits, IsDefault: b.IsDefault,
	}))
}

func (s *Store) UpdateBuild(ctx context.Context, b *domain.AgentBuild) error {
	return affected(s.q().UpdateBuild(ctx, db.UpdateBuildParams{
		ID: b.ID, UserID: b.UserID, Name: b.Name, LlmConnectionID: b.LlmConnectionID,
		SandboxConnectionID: b.SandboxConnectionID, Prompt: b.Prompt, MemoryPreset: b.MemoryPreset,
		Limits: b.Limits, IsDefault: b.IsDefault,
	}))
}

func (s *Store) DeleteBuild(ctx context.Context, id, userID int64) error {
	return affected(s.q().DeleteBuild(ctx, db.DeleteBuildParams{ID: id, UserID: userID}))
}

// ── Connections ─────────────────────────────────────────────────────────────

func (s *Store) LlmConnections(ctx context.Context, userID int64) ([]domain.LlmConnection, error) {
	rows, err := s.q().LlmConnections(ctx, userID)
	return mapRows(rows, err, func(r db.HubLlmConnection) domain.LlmConnection { return domain.LlmConnection(r) })
}

func (s *Store) CreateLlmConnection(ctx context.Context, c *domain.LlmConnection) (int64, error) {
	return s.q().CreateLlmConnection(ctx, db.CreateLlmConnectionParams{
		UserID: c.UserID, Name: c.Name, APIBase: c.APIBase, APIKeyEnc: c.APIKeyEnc, Model: c.Model,
	})
}

func (s *Store) DeleteLlmConnection(ctx context.Context, id, userID int64) error {
	return affected(s.q().DeleteLlmConnection(ctx, db.DeleteLlmConnectionParams{ID: id, UserID: userID}))
}

func (s *Store) SandboxConnections(ctx context.Context) ([]domain.SandboxConnection, error) {
	rows, err := s.q().SandboxConnections(ctx)
	return mapRows(rows, err, func(r db.HubSandboxConnection) domain.SandboxConnection { return domain.SandboxConnection(r) })
}

func (s *Store) SandboxConnection(ctx context.Context, id int64) (*domain.SandboxConnection, error) {
	c, err := optional(s.q().SandboxConnection(ctx, id))
	if c == nil || err != nil {
		return nil, err
	}
	return (*domain.SandboxConnection)(c), nil
}

func (s *Store) CreateSandboxConnection(ctx context.Context, c *domain.SandboxConnection) (int64, error) {
	return s.q().CreateSandboxConnection(ctx, db.CreateSandboxConnectionParams{
		Name: c.Name, Domain: c.Domain, APIKeyEnc: c.APIKeyEnc, Image: c.Image,
	})
}

func (s *Store) DeleteSandboxConnection(ctx context.Context, id int64) error {
	return affected(s.q().DeleteSandboxConnection(ctx, id))
}

// ── Instances ───────────────────────────────────────────────────────────────

func (s *Store) Instances(ctx context.Context, userID int64, repositoryID *int64) ([]domain.AgentInstance, error) {
	rows, err := s.q().Instances(ctx, db.InstancesParams{UserID: userID, RepositoryID: repositoryID})
	return mapRows(rows, err, func(r db.InstancesRow) domain.AgentInstance { return domain.AgentInstance(r) })
}

func (s *Store) Instance(ctx context.Context, id, userID int64) (*domain.AgentInstance, error) {
	i, err := optional(s.q().Instance(ctx, db.InstanceParams{ID: id, UserID: userID}))
	if i == nil || err != nil {
		return nil, err
	}
	return (*domain.AgentInstance)(i), nil
}

// Activity — реплей activity-кадров хода (тикет 012); eventID nil — последний ход.
func (s *Store) Activity(ctx context.Context, instanceID int64, eventID *int64) ([][]byte, error) {
	if eventID == nil {
		return s.q().ActivityLatest(ctx, instanceID)
	}
	return s.q().ActivityByEvent(ctx, db.ActivityByEventParams{InstanceID: instanceID, EventID: eventID})
}

func (s *Store) Messages(ctx context.Context, instanceID int64, before *int64, limit int32) ([]domain.ChatMessage, error) {
	rows, err := s.q().Messages(ctx, db.MessagesParams{InstanceID: instanceID, Before: before, Lim: limit})
	if err != nil {
		return nil, err
	}
	out := make([]domain.ChatMessage, 0, len(rows))
	for _, r := range rows {
		out = append(out, domain.ChatMessage{
			ID: r.ID, EventID: r.EventID, Kind: r.Kind, Payload: r.Payload, CreatedAt: r.CreatedAt,
			TraceID: r.TraceID, Action: r.Action, CommitSHA: r.CommitSHA,
		})
	}
	return out, nil
}

// threadID — тред чекпоинтов Экземпляра (Сборка, Репозиторий); один и тот же
// у Ingest и UpsertInstance — иначе разъедутся на ON CONFLICT.
func threadID(buildID, repositoryID int64) string {
	return fmt.Sprintf("hub-%d-%d", buildID, repositoryID)
}

func (s *Store) UpsertInstance(ctx context.Context, buildID, repositoryID int64) (int64, error) {
	row, err := s.q().UpsertInstance(ctx, db.UpsertInstanceParams{
		BuildID: buildID, RepositoryID: repositoryID, ThreadID: threadID(buildID, repositoryID),
	})
	return row.ID, err
}

func (s *Store) SetInstanceRunning(ctx context.Context, id, runnerID int64) error {
	return s.q().SetInstanceRunning(ctx, db.SetInstanceRunningParams{ID: id, RunnerID: runnerID})
}

func (s *Store) SetInstanceDown(ctx context.Context, id int64) error {
	return s.q().SetInstanceDown(ctx, id)
}

func (s *Store) LinkInstanceSandbox(ctx context.Context, instanceID, sandboxInstanceID, userID int64) error {
	return affected(s.q().LinkInstanceSandbox(ctx, db.LinkInstanceSandboxParams{
		ID: instanceID, SandboxInstanceID: sandboxInstanceID, UserID: userID,
	}))
}

func (s *Store) Reports(ctx context.Context, instanceID int64) ([]domain.Report, error) {
	rows, err := s.q().Reports(ctx, instanceID)
	return mapRows(rows, err, func(r db.ReportsRow) domain.Report { return reportFrom(db.RepositoryReportsRow(r)) })
}

func (s *Store) RepositoryReports(ctx context.Context, repositoryID int64) ([]domain.Report, error) {
	rows, err := s.q().RepositoryReports(ctx, repositoryID)
	return mapRows(rows, err, reportFrom)
}

func reportFrom(r db.RepositoryReportsRow) domain.Report {
	return domain.Report{
		ID: r.ID, InstanceID: r.InstanceID, EventID: r.EventID, Summary: r.Summary, CreatedAt: r.CreatedAt,
		Structured: r.Structured, CommitSHA: r.CommitSHA, Ref: r.Ref, Action: r.Action,
	}
}

func (s *Store) Findings(ctx context.Context, f domain.FindingFilter) ([]domain.Finding, error) {
	rows, err := s.q().Findings(ctx, db.FindingsParams(f))
	return mapRows(rows, err, func(r db.HubFinding) domain.Finding { return domain.Finding(r) })
}

// ── Sandbox instances (владение — юзер/hub; раннер только читает) ──────────

func (s *Store) SandboxInstances(ctx context.Context) ([]domain.SandboxInstance, error) {
	rows, err := s.q().SandboxInstances(ctx)
	return mapRows(rows, err, func(r db.HubSandboxInstance) domain.SandboxInstance { return domain.SandboxInstance(r) })
}

func (s *Store) SandboxInstance(ctx context.Context, id int64) (*domain.SandboxInstance, error) {
	si, err := optional(s.q().SandboxInstance(ctx, id))
	if si == nil || err != nil {
		return nil, err
	}
	return (*domain.SandboxInstance)(si), nil
}

func (s *Store) CreateSandboxInstance(ctx context.Context, externalID string, connectionID int64) (int64, error) {
	return conflictOnFK(s.q().CreateSandboxInstance(ctx, db.CreateSandboxInstanceParams{
		ExternalID: externalID, SandboxConnectionID: connectionID,
	}))
}

func (s *Store) MarkSandboxInstanceDead(ctx context.Context, id int64) error {
	return s.q().MarkSandboxInstanceDead(ctx, id)
}

// ── Runners и надзор за heartbeat ───────────────────────────────────────────

func (s *Store) Upsert(ctx context.Context, r domain.Runner) (int64, error) {
	return s.q().UpsertRunner(ctx, db.UpsertRunnerParams{Name: r.Name, Address: r.Address, Slots: r.Slots})
}

func (s *Store) Heartbeat(ctx context.Context, id int64) (bool, error) {
	n, err := s.q().HeartbeatRunner(ctx, id)
	return n > 0, err
}

func (s *Store) Runners(ctx context.Context) ([]domain.Runner, error) {
	rows, err := s.q().Runners(ctx)
	return mapRows(rows, err, func(r db.RunnersRow) domain.Runner { return domain.Runner(r) })
}

func (s *Store) Runner(ctx context.Context, id int64) (*domain.Runner, error) {
	r, err := optional(s.q().Runner(ctx, id))
	if r == nil || err != nil {
		return nil, err
	}
	return (*domain.Runner)(r), nil
}

func (s *Store) AliveRunner(ctx context.Context, aliveWithin time.Duration) (*domain.Runner, error) {
	r, err := optional(s.q().AliveRunner(ctx, aliveWithin))
	if r == nil || err != nil {
		return nil, err
	}
	return (*domain.Runner)(r), nil
}

// RequeueStale — running-Экземпляры протухших Раннеров → down, их
// необработанные События — снова в outbox (один стейтмент, queries/runners.sql).
func (s *Store) RequeueStale(ctx context.Context, timeout time.Duration) (int, []string, error) {
	r, err := s.q().RequeueStale(ctx, timeout)
	return r.Downed, r.RequeuedTraceIds, err
}

// RequeueInstance — «Продолжить»: незавершённые События одного Экземпляра —
// снова в outbox; возвращает пере-опубликованные eventId (пусто = нечего продолжать).
func (s *Store) RequeueInstance(ctx context.Context, instanceID int64) ([]int64, error) {
	return s.q().RequeueInstance(ctx, instanceID)
}
