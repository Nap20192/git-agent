package runnerapi

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/vnkjd/git-agent/backend/pkg/trace"
)

// Прокси в раннер несёт X-Trace-Id из ctx: raise и SSE-стримы (chat/activity).
func TestClientForwardsTraceID(t *testing.T) {
	const traceID = "0123456789abcdef0123456789abcdef"
	got := map[string]string{}
	runner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got[r.URL.Path] = r.Header.Get(trace.Header)
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: {\"kind\":\"done\"}\n\n")
	}))
	defer runner.Close()

	ctx := trace.WithValue(context.Background(), traceID)
	c := &Client{}
	if _, err := c.Raise(ctx, runner.URL, 3); err != nil {
		t.Fatal(err)
	}
	stream, err := c.Chat(ctx, runner.URL, 3, "hi")
	if err != nil {
		t.Fatal(err)
	}
	stream.Close()
	stream, err = c.Activity(ctx, runner.URL, 3, nil)
	if err != nil {
		t.Fatal(err)
	}
	stream.Close()
	for _, p := range []string{"/instances/3/raise", "/instances/3/chat", "/instances/3/activity"} {
		if got[p] != traceID {
			t.Errorf("%s: trace %q", p, got[p])
		}
	}
}
