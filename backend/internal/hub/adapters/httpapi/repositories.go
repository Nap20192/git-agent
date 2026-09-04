package httpapi

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// Подключённые Репозитории.

const eventsPageLimit = 100

type repositoryDTO struct {
	ID            int64     `json:"id"`
	IdentityID    *int64    `json:"identityId"` // null у watch-репо
	Mode          string    `json:"mode"`       // hook | watch (тикет 015)
	Provider      string    `json:"provider"`
	ExternalID    string    `json:"externalId"`
	Owner         string    `json:"owner"`
	Name          string    `json:"name"`
	DefaultBranch *string   `json:"defaultBranch"`
	BuildID       *int64    `json:"buildId"`
	ConnectedAt   time.Time `json:"connectedAt"`
}

func toRepositoryDTO(r domain.Repository) repositoryDTO {
	return repositoryDTO{
		ID: r.ID, IdentityID: r.IdentityID, Mode: r.Mode, Provider: r.Provider, ExternalID: r.ExternalID,
		Owner: r.Owner, Name: r.Name, DefaultBranch: r.DefaultBranch,
		BuildID: r.BuildID, ConnectedAt: r.ConnectedAt,
	}
}

type eventDTO struct {
	ID         int64     `json:"id"`
	Provider   string    `json:"provider"`
	Action     string    `json:"action"`
	CommitSHA  *string   `json:"commitSha"`
	Ref        *string   `json:"ref"`
	ReceivedAt time.Time `json:"receivedAt"`
	TraceID    string    `json:"traceId"`
	// diff-контекст (миграция 006)
	BeforeSHA    *string         `json:"beforeSha"`
	BaseSHA      *string         `json:"baseSha"`
	HeadSHA      *string         `json:"headSha"`
	PRNumber     *int            `json:"prNumber"`
	PRTitle      *string         `json:"prTitle"`
	PRBody       *string         `json:"prBody"`
	ChangedFiles json.RawMessage `json:"changedFiles"`
}

type triggerResultDTO struct {
	CommitSHA   string  `json:"commitSha"`
	Duplicate   bool    `json:"duplicate"`
	InstanceIDs []int64 `json:"instanceIds"`
}

func (s *Server) ownRepo(r *http.Request) (int64, error) {
	id, err := pathID(r)
	if err != nil {
		return 0, err
	}
	if _, err := found(s.Store.Repository(r.Context(), id, userID(r))); err != nil {
		return 0, err
	}
	return id, nil
}

// GET /api/repositories.
func (s *Server) listRepositories(w http.ResponseWriter, r *http.Request) error {
	list, err := s.Store.Repositories(r.Context(), userID(r))
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(list, toRepositoryDTO))
}

// POST /api/repositories — {identityId, externalId} (mode=hook, хук ставит hub)
// либо {url} (mode=watch: чужой публичный репо, без хука; тикет 015).
func (s *Server) connectRepository(w http.ResponseWriter, r *http.Request) error {
	var req struct {
		IdentityID int64  `json:"identityId"`
		ExternalID string `json:"externalId"`
		URL        string `json:"url"`
		BuildID    *int64 `json:"buildId"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	var repo *domain.Repository
	var err error
	switch {
	case req.URL != "":
		repo, err = s.Repositories.ConnectPublic(r.Context(), userID(r), req.URL, req.BuildID)
	case req.IdentityID != 0 && req.ExternalID != "":
		repo, err = s.Repositories.Connect(r.Context(), userID(r), req.IdentityID, req.ExternalID, req.BuildID)
	default:
		return domain.Invalid("either {identityId, externalId} or {url} is required")
	}
	if err != nil {
		return err
	}
	return respond(w, http.StatusCreated, toRepositoryDTO(*repo))
}

// PATCH /api/repositories/{id}.
func (s *Server) patchRepository(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	var req struct {
		BuildID *int64 `json:"buildId"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	if req.BuildID == nil {
		return domain.Invalid("deprecated route: manage subscriptions via /api/repositories/{id}/subscriptions")
	}
	repo, err := s.Repositories.SetBuild(r.Context(), id, userID(r), *req.BuildID)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, toRepositoryDTO(*repo))
}

// DELETE /api/repositories/{id}.
func (s *Server) disconnectRepository(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	if err := s.Repositories.Disconnect(r.Context(), id, userID(r)); err != nil {
		return err
	}
	return noContent(w)
}

// POST /api/repositories/{id}/trigger.
func (s *Server) triggerRepository(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	var req struct {
		Ref       string `json:"ref"`
		CommitSHA string `json:"commitSha"`
		Mode      string `json:"mode"`
	}
	if err := decodeOptional(r, &req); err != nil {
		return err
	}
	if req.Mode != "" && req.Mode != "manual" && req.Mode != "full" {
		return domain.Invalid("mode must be manual or full")
	}
	res, err := s.Repositories.Trigger(r.Context(), userID(r), id, req.Ref, req.CommitSHA, req.Mode)
	if err != nil {
		return err
	}
	return respond(w, http.StatusAccepted, triggerResultDTO{
		CommitSHA:   res.CommitSHA,
		Duplicate:   res.Duplicate,
		InstanceIDs: append([]int64{}, res.InstanceIDs...), // [] вместо null в JSON
	})
}

// GET /api/repositories/{id}/events.
func (s *Server) repositoryEvents(w http.ResponseWriter, r *http.Request) error {
	id, err := s.ownRepo(r)
	if err != nil {
		return err
	}
	events, err := s.Store.Events(r.Context(), id, eventsPageLimit)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(events, func(e domain.EventRecord) eventDTO { return eventDTO(e) }))
}

// POST /api/repositories/{id}/raise — поднять агента без скана: Экземпляры
// Сборок, что отвечают за репо (как у run agent), создаются и поднимаются
// на Раннере; Событие не публикуется. instances пуст — никто не обслуживает.
func (s *Server) raiseRepository(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	repo, err := found(s.Store.Repository(r.Context(), id, userID(r)))
	if err != nil {
		return err
	}
	ref := ""
	if repo.DefaultBranch != nil {
		ref = *repo.DefaultBranch
	}
	buildIDs, err := s.Webhook.MatchedBuilds(r.Context(), repo, "manual", ref)
	if err != nil {
		return err
	}
	raised, err := s.Instances.RaiseForRepository(r.Context(), repo, buildIDs, userID(r))
	if err != nil {
		return err
	}
	type item struct {
		ID     int64  `json:"id"`
		Status string `json:"status"`
	}
	items := mapSlice(raised, func(x app.RaisedInstance) item {
		st := "running"
		if x.Queued {
			st = "queued"
		}
		return item{ID: x.ID, Status: st}
	})
	return respond(w, http.StatusOK, map[string]any{"instances": items})
}

// GET /api/repositories/{id}/reports — отчёты всех Экземпляров репо, новые сверху
// (eventId → коммит берётся из журнала Событий).
func (s *Server) repositoryReports(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	if _, err := found(s.Store.Repository(r.Context(), id, userID(r))); err != nil {
		return err
	}
	reports, err := s.Store.RepositoryReports(r.Context(), id)
	if err != nil {
		return err
	}
	return respond(w, http.StatusOK, mapSlice(reports, func(rep domain.Report) reportDTO { return reportDTO(rep) }))
}
