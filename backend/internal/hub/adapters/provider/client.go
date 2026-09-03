// Package provider — outbound-адаптер API GitHub/GitLab: список репозиториев
// связки и управление вебхуками (тикет 002: хук вешает сам backend, на все
// действия). Базовые URL переопределяемы — для тестов с httptest.
package provider

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/trace"
)

type Client struct {
	GitHubBase string // default https://api.github.com
	GitLabBase string // default https://gitlab.com/api/v4
	HTTP       *http.Client
}

var _ domain.ProviderClient = (*Client)(nil)

func (c *Client) github() string {
	if c.GitHubBase != "" {
		return c.GitHubBase
	}
	return "https://api.github.com"
}

func (c *Client) gitlab() string {
	if c.GitLabBase != "" {
		return c.GitLabBase
	}
	return "https://gitlab.com/api/v4"
}

func (c *Client) http() *http.Client {
	if c.HTTP != nil {
		return c.HTTP
	}
	return &http.Client{Timeout: 30 * time.Second}
}

// do — запрос с Bearer-токеном связки (пустой токен — публичный API без
// авторизации, тикет 015); тело ответа декодируется в out (если не nil).
func (c *Client) do(ctx context.Context, token, method, url string, body, out any) error {
	var reqBody io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reqBody = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, url, reqBody)
	if err != nil {
		return err
	}
	if id := trace.FromContext(ctx); id != "" {
		req.Header.Set(trace.Header, id)
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.http().Do(req)
	if err != nil {
		return fmt.Errorf("provider unreachable: %w: %w", err, domain.ErrUpstream)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusUnauthorized {
		// сигнал refresh-флоу (тикет 003)
		return fmt.Errorf("provider %s %s: token rejected (401): %w", method, url, domain.ErrUnauthorized)
	}
	if resp.StatusCode == http.StatusNotFound {
		// репо/ветка/хук не существует или невидим без прав — 404 наружу, не 502
		return fmt.Errorf("provider %s %s: not found (404): %w", method, url, domain.ErrNotFound)
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("provider %s %s: status %d: %s: %w", method, url, resp.StatusCode, msg, domain.ErrUpstream)
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

type githubRepo struct {
	ID    int64  `json:"id"`
	Name  string `json:"name"`
	Owner struct {
		Login string `json:"login"`
	} `json:"owner"`
	DefaultBranch *string `json:"default_branch"`
	Private       bool    `json:"private"`
}

func (g githubRepo) toDomain() domain.ProviderRepo {
	return domain.ProviderRepo{
		ExternalID:    strconv.FormatInt(g.ID, 10),
		Owner:         g.Owner.Login,
		Name:          g.Name,
		DefaultBranch: g.DefaultBranch,
		Private:       g.Private,
	}
}

type gitlabRepo struct {
	ID        int64  `json:"id"`
	Path      string `json:"path"`
	Namespace struct {
		FullPath string `json:"full_path"`
	} `json:"namespace"`
	DefaultBranch *string `json:"default_branch"`
	Visibility    string  `json:"visibility"`
}

func (g gitlabRepo) toDomain() domain.ProviderRepo {
	return domain.ProviderRepo{
		ExternalID:    strconv.FormatInt(g.ID, 10),
		Owner:         g.Namespace.FullPath,
		Name:          g.Path,
		DefaultBranch: g.DefaultBranch,
		Private:       g.Visibility != "public",
	}
}

func (c *Client) Repos(ctx context.Context, providerName, token string) ([]domain.ProviderRepo, error) {
	// ponytail: одна страница на 100 — пагинация, когда упрёмся в реальный аккаунт крупнее
	switch providerName {
	case "github":
		var list []githubRepo
		if err := c.do(ctx, token, "GET", c.github()+"/user/repos?per_page=100&sort=updated", nil, &list); err != nil {
			return nil, err
		}
		out := make([]domain.ProviderRepo, len(list))
		for i, r := range list {
			out[i] = r.toDomain()
		}
		return out, nil
	case "gitlab":
		var list []gitlabRepo
		if err := c.do(ctx, token, "GET", c.gitlab()+"/projects?membership=true&per_page=100&order_by=last_activity_at", nil, &list); err != nil {
			return nil, err
		}
		out := make([]domain.ProviderRepo, len(list))
		for i, r := range list {
			out[i] = r.toDomain()
		}
		return out, nil
	}
	return nil, fmt.Errorf("unknown provider %q", providerName)
}

func (c *Client) Repo(ctx context.Context, providerName, token, externalID string) (*domain.ProviderRepo, error) {
	switch providerName {
	case "github":
		var r githubRepo
		if err := c.do(ctx, token, "GET", c.github()+"/repositories/"+url.PathEscape(externalID), nil, &r); err != nil {
			return nil, err
		}
		repo := r.toDomain()
		return &repo, nil
	case "gitlab":
		var r gitlabRepo
		if err := c.do(ctx, token, "GET", c.gitlab()+"/projects/"+url.PathEscape(externalID), nil, &r); err != nil {
			return nil, err
		}
		repo := r.toDomain()
		return &repo, nil
	}
	return nil, fmt.Errorf("unknown provider %q", providerName)
}

// RepoByPath — репо по owner/name (публичный API при пустом токене, тикет 015).
func (c *Client) RepoByPath(ctx context.Context, providerName, token, owner, name string) (*domain.ProviderRepo, error) {
	switch providerName {
	case "github":
		var r githubRepo
		u := fmt.Sprintf("%s/repos/%s/%s", c.github(), url.PathEscape(owner), url.PathEscape(name))
		if err := c.do(ctx, token, "GET", u, nil, &r); err != nil {
			return nil, err
		}
		repo := r.toDomain()
		return &repo, nil
	case "gitlab":
		var r gitlabRepo
		if err := c.do(ctx, token, "GET", c.gitlab()+"/projects/"+url.PathEscape(owner+"/"+name), nil, &r); err != nil {
			return nil, err
		}
		repo := r.toDomain()
		return &repo, nil
	}
	return nil, fmt.Errorf("unknown provider %q", providerName)
}

func (c *Client) CreateHook(ctx context.Context, providerName, token string, repo domain.ProviderRepo, hookURL, secret string) (string, error) {
	var out struct {
		ID int64 `json:"id"`
	}
	switch providerName {
	case "github":
		body := map[string]any{
			"name":   "web",
			"active": true,
			"events": []string{"*"}, // все действия — тикет 002
			"config": map[string]any{"url": hookURL, "content_type": "json", "secret": secret},
		}
		u := fmt.Sprintf("%s/repos/%s/%s/hooks", c.github(), url.PathEscape(repo.Owner), url.PathEscape(repo.Name))
		if err := c.do(ctx, token, "POST", u, body, &out); err != nil {
			return "", err
		}
	case "gitlab":
		body := map[string]any{
			"url": hookURL, "token": secret,
			"push_events": true, "tag_push_events": true, "merge_requests_events": true,
			"issues_events": true, "note_events": true, "pipeline_events": true, "releases_events": true,
		}
		u := c.gitlab() + "/projects/" + url.PathEscape(repo.ExternalID) + "/hooks"
		if err := c.do(ctx, token, "POST", u, body, &out); err != nil {
			return "", err
		}
	default:
		return "", fmt.Errorf("unknown provider %q", providerName)
	}
	return strconv.FormatInt(out.ID, 10), nil
}

func (c *Client) BranchHead(ctx context.Context, providerName, token string, repo *domain.Repository, ref string) (string, error) {
	switch providerName {
	case "github":
		var out struct {
			SHA string `json:"sha"`
		}
		u := fmt.Sprintf("%s/repos/%s/%s/commits/%s",
			c.github(), url.PathEscape(repo.Owner), url.PathEscape(repo.Name), url.PathEscape(ref))
		if err := c.do(ctx, token, "GET", u, nil, &out); err != nil {
			return "", err
		}
		return out.SHA, nil
	case "gitlab":
		var out struct {
			ID string `json:"id"`
		}
		u := c.gitlab() + "/projects/" + url.PathEscape(repo.ExternalID) + "/repository/commits/" + url.PathEscape(ref)
		if err := c.do(ctx, token, "GET", u, nil, &out); err != nil {
			return "", err
		}
		return out.ID, nil
	}
	return "", fmt.Errorf("unknown provider %q", providerName)
}

func (c *Client) DeleteHook(ctx context.Context, providerName, token string, repo *domain.Repository, hookID string) error {
	switch providerName {
	case "github":
		u := fmt.Sprintf("%s/repos/%s/%s/hooks/%s",
			c.github(), url.PathEscape(repo.Owner), url.PathEscape(repo.Name), url.PathEscape(hookID))
		return c.do(ctx, token, "DELETE", u, nil, nil)
	case "gitlab":
		u := c.gitlab() + "/projects/" + url.PathEscape(repo.ExternalID) + "/hooks/" + url.PathEscape(hookID)
		return c.do(ctx, token, "DELETE", u, nil, nil)
	}
	return fmt.Errorf("unknown provider %q", providerName)
}
