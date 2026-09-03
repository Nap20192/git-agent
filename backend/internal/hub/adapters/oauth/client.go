// Package oauth — outbound-адаптер OAuth-флоу GitHub/GitLab (тикет 003).
// Провайдер без client_id/secret недоступен (ErrUnavailable), не ошибка старта.
// Базовые URL переопределяемы — для тестов с httptest.
package oauth

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

type App struct{ ClientID, ClientSecret string }

func (a App) configured() bool { return a.ClientID != "" && a.ClientSecret != "" }

type Client struct {
	GitHub App
	GitLab App

	GitHubWeb string // default https://github.com
	GitHubAPI string // default https://api.github.com
	GitLabURL string // default https://gitlab.com
	HTTP      *http.Client
}

var _ domain.OAuthClient = (*Client)(nil)

func (c *Client) http() *http.Client {
	if c.HTTP != nil {
		return c.HTTP
	}
	return &http.Client{Timeout: 30 * time.Second}
}

func (c *Client) githubWeb() string { return defaultStr(c.GitHubWeb, "https://github.com") }
func (c *Client) githubAPI() string { return defaultStr(c.GitHubAPI, "https://api.github.com") }
func (c *Client) gitlabURL() string { return defaultStr(c.GitLabURL, "https://gitlab.com") }

func defaultStr(v, def string) string {
	if v != "" {
		return v
	}
	return def
}

func (c *Client) app(provider string) (App, error) {
	switch provider {
	case "github":
		if c.GitHub.configured() {
			return c.GitHub, nil
		}
	case "gitlab":
		if c.GitLab.configured() {
			return c.GitLab, nil
		}
	default:
		return App{}, fmt.Errorf("unknown provider %q", provider)
	}
	return App{}, fmt.Errorf("%s oauth app is not configured: %w", provider, domain.ErrUnavailable)
}

func (c *Client) AuthURL(provider, redirectURI, state string) (string, error) {
	app, err := c.app(provider)
	if err != nil {
		return "", err
	}
	q := url.Values{
		"client_id":    {app.ClientID},
		"redirect_uri": {redirectURI},
		"state":        {state},
	}
	switch provider {
	case "github":
		q.Set("scope", "repo read:user")
		return c.githubWeb() + "/login/oauth/authorize?" + q.Encode(), nil
	default: // gitlab
		q.Set("response_type", "code")
		q.Set("scope", "api")
		return c.gitlabURL() + "/oauth/authorize?" + q.Encode(), nil
	}
}

func (c *Client) Exchange(ctx context.Context, provider, code, redirectURI string) (*domain.OAuthToken, error) {
	app, err := c.app(provider)
	if err != nil {
		return nil, err
	}
	form := url.Values{
		"client_id":     {app.ClientID},
		"client_secret": {app.ClientSecret},
		"code":          {code},
		"redirect_uri":  {redirectURI},
	}
	tokenURL := c.githubWeb() + "/login/oauth/access_token"
	if provider == "gitlab" {
		form.Set("grant_type", "authorization_code")
		tokenURL = c.gitlabURL() + "/oauth/token"
	}
	return c.token(ctx, tokenURL, form)
}

func (c *Client) Refresh(ctx context.Context, provider, refreshToken string) (*domain.OAuthToken, error) {
	app, err := c.app(provider)
	if err != nil {
		return nil, err
	}
	if provider != "gitlab" {
		// у GitHub OAuth App access-токены вечные — refresh не нужен
		return nil, fmt.Errorf("refresh is not supported for %s", provider)
	}
	return c.token(ctx, c.gitlabURL()+"/oauth/token", url.Values{
		"client_id":     {app.ClientID},
		"client_secret": {app.ClientSecret},
		"grant_type":    {"refresh_token"},
		"refresh_token": {refreshToken},
	})
}

func (c *Client) token(ctx context.Context, tokenURL string, form url.Values) (*domain.OAuthToken, error) {
	req, err := http.NewRequestWithContext(ctx, "POST", tokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/json")
	resp, err := c.http().Do(req)
	if err != nil {
		return nil, fmt.Errorf("oauth token endpoint unreachable: %v: %w", err, domain.ErrUpstream)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("oauth token endpoint: status %d: %s: %w", resp.StatusCode, msg, domain.ErrUpstream)
	}
	var body struct {
		AccessToken  string `json:"access_token"`
		RefreshToken string `json:"refresh_token"`
		ExpiresIn    int64  `json:"expires_in"`
		Error        string `json:"error"`
		ErrorDesc    string `json:"error_description"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, err
	}
	if body.Error != "" {
		return nil, fmt.Errorf("oauth token endpoint: %s: %s: %w", body.Error, body.ErrorDesc, domain.ErrUpstream)
	}
	if body.AccessToken == "" {
		return nil, fmt.Errorf("oauth token endpoint: empty access_token: %w", domain.ErrUpstream)
	}
	tok := &domain.OAuthToken{AccessToken: body.AccessToken, RefreshToken: body.RefreshToken}
	if body.ExpiresIn > 0 {
		t := time.Now().Add(time.Duration(body.ExpiresIn) * time.Second)
		tok.ExpiresAt = &t
	}
	return tok, nil
}

func (c *Client) UserInfo(ctx context.Context, provider, accessToken string) (string, string, error) {
	var userURL string
	switch provider {
	case "github":
		userURL = c.githubAPI() + "/user"
	case "gitlab":
		userURL = c.gitlabURL() + "/api/v4/user"
	default:
		return "", "", fmt.Errorf("unknown provider %q", provider)
	}
	req, err := http.NewRequestWithContext(ctx, "GET", userURL, nil)
	if err != nil {
		return "", "", err
	}
	req.Header.Set("Authorization", "Bearer "+accessToken)
	req.Header.Set("Accept", "application/json")
	resp, err := c.http().Do(req)
	if err != nil {
		return "", "", fmt.Errorf("oauth userinfo unreachable: %v: %w", err, domain.ErrUpstream)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return "", "", fmt.Errorf("oauth userinfo: status %d: %w", resp.StatusCode, domain.ErrUpstream)
	}
	var u struct {
		ID       int64  `json:"id"`
		Login    string `json:"login"`    // github
		Username string `json:"username"` // gitlab
	}
	if err := json.NewDecoder(resp.Body).Decode(&u); err != nil {
		return "", "", err
	}
	username := u.Login
	if username == "" {
		username = u.Username
	}
	if u.ID == 0 || username == "" {
		return "", "", fmt.Errorf("oauth userinfo: incomplete profile: %w", domain.ErrUpstream)
	}
	return strconv.FormatInt(u.ID, 10), username, nil
}
