// Package runnerapi — outbound-адаптер API Раннера (тикет 004): raise/stop
// Экземпляра и SSE-чат. Контракт кадров чата — ChatEvent в backend/docs/openapi.yaml;
// hub проксирует поток раннера как есть.
package runnerapi

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

type Client struct {
	HTTP *http.Client
	// FirstByteTimeout — сколько ждать первого байта SSE-чата: раннер при
	// занятых слотах ставит запрос в очередь, а не отказывает, поэтому
	// ожидание щедрое (дефолт 120s); истечение — domain.ErrTimeout (504).
	FirstByteTimeout time.Duration
}

var _ domain.RunnerClient = (*Client)(nil)

func (c *Client) firstByteTimeout() time.Duration {
	if c.FirstByteTimeout > 0 {
		return c.FirstByteTimeout
	}
	return 120 * time.Second
}

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
		return nil, fmt.Errorf("runner unreachable: %v: %w", err, domain.ErrUpstream)
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
		return nil, fmt.Errorf("runner %s: status %d: %s: %w", url, resp.StatusCode, msg, domain.ErrUpstream)
	}
	return resp, nil
}

// Raise — быстрый подъём: 200 = running, 202 = queued (раннер поднимет фоном,
// когда освободится слот) — прокси не ждёт слот HTTP-запросом.
func (c *Client) Raise(ctx context.Context, addr string, instanceID int64) (bool, error) {
	resp, err := c.post(ctx, fmt.Sprintf("%s/instances/%d/raise", addr, instanceID), nil)
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusAccepted, nil
}

func (c *Client) Stop(ctx context.Context, addr string, instanceID int64) error {
	resp, err := c.post(ctx, fmt.Sprintf("%s/instances/%d/stop", addr, instanceID), nil)
	if err != nil {
		return err
	}
	return resp.Body.Close()
}

// Chat — SSE-поток раннера. Таймаут применяется только к ожиданию ПЕРВОГО
// байта (очередь на раннере), сам стрим не ограничен — им управляет ctx.
// Возврат без ошибки гарантирует, что первый кадр уже получен.
func (c *Client) Chat(ctx context.Context, addr string, instanceID int64, message string) (io.ReadCloser, error) {
	b, _ := json.Marshal(map[string]string{"message": message})

	timedOut := errors.New("first byte timeout")
	reqCtx, cancel := context.WithCancelCause(ctx)
	timer := time.AfterFunc(c.firstByteTimeout(), func() { cancel(timedOut) })

	fail := func(err error) (io.ReadCloser, error) {
		timer.Stop()
		cancel(nil)
		if errors.Is(context.Cause(reqCtx), timedOut) {
			return nil, fmt.Errorf("runner did not start streaming within %s: %w",
				c.firstByteTimeout(), domain.ErrTimeout)
		}
		return nil, err
	}

	req, err := http.NewRequestWithContext(reqCtx, "POST",
		fmt.Sprintf("%s/instances/%d/chat", addr, instanceID), bytes.NewReader(b))
	if err != nil {
		return fail(err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream")
	streamClient := &http.Client{} // без Timeout — иначе он убьёт долгий чат
	resp, err := streamClient.Do(req)
	if err != nil {
		return fail(fmt.Errorf("runner unreachable: %v: %w", err, domain.ErrUpstream))
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
		return fail(fmt.Errorf("runner chat: status %d: %s: %w", resp.StatusCode, msg, domain.ErrUpstream))
	}

	// заголовки могли прийти сразу, а первый кадр — после очереди:
	// ждём первый байт здесь, чтобы 504 ушёл ДО начала SSE-ответа клиенту
	buf := make([]byte, 4096)
	n, readErr := resp.Body.Read(buf)
	timer.Stop()
	if n == 0 && readErr != nil && readErr != io.EOF {
		resp.Body.Close()
		return fail(readErr)
	}
	return &bufferedStream{head: buf[:n], body: resp.Body, cancel: func() { cancel(nil) }}, nil
}

// Terminal — SSE-поток стрим-консоли раннера. Без first-byte-таймаута: кадры
// приходят по завершении команды, а команда может идти дольше любого
// разумного таймаута — стримом управляет ctx.
func (c *Client) Terminal(ctx context.Context, addr string, instanceID int64, command string) (io.ReadCloser, error) {
	b, _ := json.Marshal(map[string]string{"command": command})
	req, err := http.NewRequestWithContext(ctx, "POST",
		fmt.Sprintf("%s/instances/%d/terminal", addr, instanceID), bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream")
	streamClient := &http.Client{} // без Timeout — иначе он убьёт долгую команду
	resp, err := streamClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("runner unreachable: %v: %w", err, domain.ErrUpstream)
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
		return nil, fmt.Errorf("runner terminal: status %d: %s: %w", resp.StatusCode, msg, domain.ErrUpstream)
	}
	return resp.Body, nil
}

// Activity — SSE-поток activity-кадров хода (кадры ActivityEvent): живой ход
// стримится по мере появления, завершённый — реплей + done. Без first-byte
// таймаута: раннер отвечает сразу (реплей либо подписка) — стримом управляет ctx.
func (c *Client) Activity(ctx context.Context, addr string, instanceID int64, eventID *int64) (io.ReadCloser, error) {
	url := fmt.Sprintf("%s/instances/%d/activity", addr, instanceID)
	if eventID != nil {
		url = fmt.Sprintf("%s?eventId=%d", url, *eventID)
	}
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "text/event-stream")
	streamClient := &http.Client{} // без Timeout — живой ход стримится долго
	resp, err := streamClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("runner unreachable: %v: %w", err, domain.ErrUpstream)
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		resp.Body.Close()
		return nil, fmt.Errorf("runner activity: status %d: %s: %w", resp.StatusCode, msg, domain.ErrUpstream)
	}
	return resp.Body, nil
}

// bufferedStream — уже прочитанный первый кусок + остаток потока.
type bufferedStream struct {
	head   []byte
	body   io.ReadCloser
	cancel func()
}

func (s *bufferedStream) Read(p []byte) (int, error) {
	if len(s.head) > 0 {
		n := copy(p, s.head)
		s.head = s.head[n:]
		return n, nil
	}
	return s.body.Read(p)
}

func (s *bufferedStream) Close() error {
	s.cancel()
	return s.body.Close()
}
