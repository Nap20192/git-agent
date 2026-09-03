// Package runnerapi — outbound-адаптер API Раннера (тикет 004): raise/stop
// Экземпляра и SSE-чат. Контракт кадров чата — ChatEvent в backend/docs/openapi.yaml;
// hub проксирует поток раннера как есть.
package runnerapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

type Client struct {
	HTTP *http.Client
}

var _ domain.RunnerClient = (*Client)(nil)

func (c *Client) http() *http.Client {
	if c.HTTP != nil {
		return c.HTTP
	}
	return &http.Client{Timeout: 60 * time.Second}
}

func (c *Client) post(ctx context.Context, url string, body any) (*http.Response, error) {
	var reqBody io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		reqBody = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, "POST", url, reqBody)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.http().Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
		return nil, fmt.Errorf("runner %s: status %d: %s", url, resp.StatusCode, msg)
	}
	return resp, nil
}

func (c *Client) Raise(ctx context.Context, addr string, instanceID int64) error {
	resp, err := c.post(ctx, fmt.Sprintf("%s/instances/%d/raise", addr, instanceID), nil)
	if err != nil {
		return err
	}
	return resp.Body.Close()
}

func (c *Client) Stop(ctx context.Context, addr string, instanceID int64) error {
	resp, err := c.post(ctx, fmt.Sprintf("%s/instances/%d/stop", addr, instanceID), nil)
	if err != nil {
		return err
	}
	return resp.Body.Close()
}

// Chat — SSE-поток раннера; таймаут клиента не применяется (стрим),
// жизнью запроса управляет ctx.
func (c *Client) Chat(ctx context.Context, addr string, instanceID int64, message string) (io.ReadCloser, error) {
	b, _ := json.Marshal(map[string]string{"message": message})
	req, err := http.NewRequestWithContext(ctx, "POST",
		fmt.Sprintf("%s/instances/%d/chat", addr, instanceID), bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream")
	streamClient := &http.Client{} // без Timeout — иначе он убьёт долгий чат
	resp, err := streamClient.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
		return nil, fmt.Errorf("runner chat: status %d: %s", resp.StatusCode, msg)
	}
	return resp.Body, nil
}
