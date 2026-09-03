// Package opensandbox — тонкий outbound-клиент lifecycle-API OpenSandbox
// (.wayfinder/research/opensandbox-go.md): create (no-TTL) + destroy. Раннеру
// эти операции запрещены — песочницами владеет hub по команде юзера.
package opensandbox

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

const headerAPIKey = "OPEN-SANDBOX-API-KEY"

type Client struct {
	HTTP *http.Client
}

var _ domain.SandboxLifecycle = (*Client)(nil)

func (c *Client) http() *http.Client {
	if c.HTTP != nil {
		return c.HTTP
	}
	return &http.Client{Timeout: 60 * time.Second}
}

// baseURL — зеркало Python SDK get_base_url: домен без схемы → http://, + /v1.
func baseURL(domain string) string {
	if !strings.HasPrefix(domain, "http://") && !strings.HasPrefix(domain, "https://") {
		domain = "http://" + domain
	}
	return domain + "/v1"
}

func (c *Client) do(ctx context.Context, apiKey, method, url string, body, out any) error {
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
	if apiKey != "" {
		req.Header.Set(headerAPIKey, apiKey)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.http().Do(req)
	if err != nil {
		return fmt.Errorf("opensandbox unreachable: %v: %w", err, domain.ErrUpstream)
	}
	defer resp.Body.Close()
	if method == http.MethodDelete && resp.StatusCode == http.StatusNotFound {
		return nil // уже нет — идемпотентный kill
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("opensandbox %s %s: status %d: %s: %w", method, url, resp.StatusCode, msg, domain.ErrUpstream)
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func (c *Client) CreateSandbox(ctx context.Context, host, apiKey, image string) (string, error) {
	body := map[string]any{
		"image": map[string]string{"uri": image},
		// API требует entrypoint и resourceLimits вместе с image;
		// значения — как в примерах Python SDK (tail-noop, 1 cpu / 512Mi)
		"entrypoint":     []string{"tail", "-f", "/dev/null"},
		"resourceLimits": map[string]string{"cpu": "1", "memory": "512Mi"},
		"timeout":        nil, // no-TTL: жизненным циклом рулит юзер, не таймер
		// execd держит SSE-стрим команды ещё ApiGracefulShutdownTimeout (1s) после
		// execution_complete — ~1s накладных на каждую команду агента; укорачиваем
		"env": map[string]string{"EXECD_API_GRACE_SHUTDOWN": "100ms"},
	}
	var out struct {
		ID string `json:"id"`
	}
	if err := c.do(ctx, apiKey, http.MethodPost, baseURL(host)+"/sandboxes", body, &out); err != nil {
		return "", err
	}
	if out.ID == "" {
		return "", fmt.Errorf("opensandbox create: empty sandbox id in response: %w", domain.ErrUpstream)
	}
	return out.ID, nil
}

func (c *Client) DeleteSandbox(ctx context.Context, domain, apiKey, externalID string) error {
	return c.do(ctx, apiKey, http.MethodDelete, baseURL(domain)+"/sandboxes/"+externalID, nil, nil)
}
