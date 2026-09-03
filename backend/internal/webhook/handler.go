// Package webhook — приёмник вебхуков GitHub/GitLab (тикет 002).
// Наружу ВСЕГДА 200: невалидная подпись, неизвестный репо, дубль — дроп + лог.
package webhook

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/vnkjd/git-agent/backend/internal/secrets"
)

const maxBody = 10 << 20

type Handler struct {
	DB      *pgxpool.Pool
	Secrets *secrets.Box
}

// ServeHTTP — POST /hooks/{provider}/{repositoryId}.
func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	defer w.WriteHeader(http.StatusOK) // единственный ответ наружу

	provider := r.PathValue("provider")
	repoID, err := strconv.ParseInt(r.PathValue("repositoryId"), 10, 64)
	if (provider != "github" && provider != "gitlab") || err != nil {
		slog.Info("webhook: dropped, bad path", "provider", provider)
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, maxBody))
	if err != nil {
		slog.Info("webhook: dropped, body read", "err", err)
		return
	}

	ctx := r.Context()
	var (
		userID    int64
		owner     string
		name      string
		buildID   *int64
		secretEnc []byte
	)
	err = h.DB.QueryRow(ctx,
		`SELECT user_id, owner, name, build_id, webhook_secret_enc
		   FROM hub.repositories WHERE id = $1 AND provider = $2`,
		repoID, provider,
	).Scan(&userID, &owner, &name, &buildID, &secretEnc)
	if err != nil {
		slog.Info("webhook: dropped, unknown repository", "repositoryId", repoID, "provider", provider)
		return
	}
	secret, err := h.Secrets.Decrypt(secretEnc)
	if err != nil || secretEnc == nil {
		slog.Warn("webhook: dropped, no usable secret", "repositoryId", repoID)
		return
	}

	valid := false
	switch provider {
	case "github":
		valid = VerifyGitHub(body, string(secret), r.Header.Get("X-Hub-Signature-256"))
	case "gitlab":
		valid = VerifyGitLab(string(secret), r.Header.Get("X-Gitlab-Token"))
	}
	if !valid {
		slog.Warn("webhook: dropped, invalid signature", "repositoryId", repoID, "provider", provider)
		return
	}

	e, ok := Parse(provider, r.Header, body)
	if !ok {
		slog.Info("webhook: dropped, unparseable event", "repositoryId", repoID, "provider", provider)
		return
	}

	if err := h.ingest(ctx, provider, repoID, userID, owner+"/"+name, buildID, e, body); err != nil {
		slog.Error("webhook: ingest failed", "repositoryId", repoID, "deliveryId", e.DeliveryID, "err", err)
	}
}

// ingest — одна транзакция: журнал hub.events (дедуп по provider+delivery_id) +
// upsert Экземпляра Агента + строка hub.outbox с тонким Событием (тикет 001).
func (h *Handler) ingest(ctx context.Context, provider string, repoID, userID int64, repo string, buildID *int64, e Event, payload []byte) error {
	tx, err := h.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	var eventID int64
	err = tx.QueryRow(ctx,
		`INSERT INTO hub.events (provider, delivery_id, repository_id, action, commit_sha, ref, payload)
		 VALUES ($1, $2, $3, $4, NULLIF($5, ''), NULLIF($6, ''), $7)
		 ON CONFLICT (provider, delivery_id) DO NOTHING
		 RETURNING id`,
		provider, e.DeliveryID, repoID, e.Action, e.CommitSHA, e.Ref, payload,
	).Scan(&eventID)
	if errors.Is(err, pgx.ErrNoRows) {
		slog.Info("webhook: duplicate delivery", "provider", provider, "deliveryId", e.DeliveryID)
		return nil
	}
	if err != nil {
		return fmt.Errorf("insert event: %w", err)
	}

	if buildID != nil {
		var instanceID int64
		err = tx.QueryRow(ctx,
			`INSERT INTO hub.agent_instances (build_id, repository_id, thread_id)
			 VALUES ($1, $2, $3)
			 ON CONFLICT (build_id, repository_id) DO UPDATE SET updated_at = now()
			 RETURNING id`,
			*buildID, repoID, fmt.Sprintf("hub-%d-%d", *buildID, repoID),
		).Scan(&instanceID)
		if err != nil {
			return fmt.Errorf("upsert instance: %w", err)
		}
		dedupKey := e.CommitSHA
		if dedupKey == "" {
			dedupKey = strconv.FormatInt(eventID, 10)
		}
		if _, err := tx.Exec(ctx,
			`INSERT INTO hub.instance_events (instance_id, event_id, dedup_key)
			 VALUES ($1, $2, $3) ON CONFLICT DO NOTHING`,
			instanceID, eventID, dedupKey,
		); err != nil {
			return fmt.Errorf("insert instance event: %w", err)
		}
	}

	thin, _ := json.Marshal(map[string]any{
		"eventId":      eventID,
		"provider":     provider,
		"repositoryId": repoID,
		"repo":         repo,
		"action":       e.Action,
		"commitSha":    e.CommitSHA,
		"ref":          e.Ref,
		"userId":       userID,
	})
	if _, err := tx.Exec(ctx,
		`INSERT INTO hub.outbox (event_id, routing_key, payload) VALUES ($1, $2, $3)`,
		eventID, RoutingKey(provider, repoID, e.Action), thin,
	); err != nil {
		return fmt.Errorf("insert outbox: %w", err)
	}
	return tx.Commit(ctx)
}
