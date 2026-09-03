package app

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/runnerapi"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
)

// seedInstance — минимальная цепочка до down-Экземпляра; возвращает (userID, instanceID).
func seedInstance(t *testing.T, db *pgxpool.Pool) (int64, int64) {
	t.Helper()
	var userID, instID int64
	err := db.QueryRow(context.Background(), `
		WITH u AS (INSERT INTO hub.users (display_name) VALUES ('t') RETURNING id),
		i AS (INSERT INTO hub.identities (user_id, provider, provider_user_id, username, access_token_enc)
		      SELECT id, 'github', 'gh-1', 't', '\x00' FROM u RETURNING id, user_id),
		l AS (INSERT INTO hub.llm_connections (user_id, name, api_base, api_key_enc, model)
		      SELECT id, 'llm', 'http://x', '\x00', 'm' FROM u RETURNING id, user_id),
		s AS (INSERT INTO hub.sandbox_connections (name, domain) VALUES ('sbx', 'x') RETURNING id),
		b AS (INSERT INTO hub.agent_builds (user_id, name, llm_connection_id, sandbox_connection_id)
		      SELECT l.user_id, 'default', l.id, s.id FROM l, s RETURNING id, user_id),
		r AS (INSERT INTO hub.repositories (user_id, identity_id, provider, external_id, owner, name)
		      SELECT b.user_id, i.id, 'github', '100', 'acme', 'repo' FROM b, i RETURNING id)
		INSERT INTO hub.agent_instances (build_id, repository_id, thread_id)
		SELECT b.id, r.id, 'thr-1' FROM b, r RETURNING id, (SELECT user_id FROM b)`,
	).Scan(&instID, &userID)
	if err != nil {
		t.Fatal(err)
	}
	return userID, instID
}

// Чат с down-Экземпляром: hub делает raise на Раннере со свободным слотом,
// фиксирует running в БД и проксирует SSE-поток раннера.
func TestChatRaisesDownInstance(t *testing.T) {
	db := testdb.Setup(t)
	userID, instID := seedInstance(t, db)

	var raised, stopped atomic.Int64
	fakeRunner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case fmt.Sprintf("/instances/%d/raise", instID):
			raised.Add(1)
			w.WriteHeader(http.StatusOK)
		case fmt.Sprintf("/instances/%d/chat", instID):
			w.Header().Set("Content-Type", "text/event-stream")
			fmt.Fprint(w, "data: {\"kind\":\"token\",\"text\":\"hi\"}\n\n")
			fmt.Fprint(w, "data: {\"kind\":\"done\"}\n\n")
		case fmt.Sprintf("/instances/%d/stop", instID):
			stopped.Add(1)
			w.WriteHeader(http.StatusOK)
		default:
			t.Errorf("unexpected runner call: %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer fakeRunner.Close()

	store := &pgstore.Store{Pool: db}
	if _, err := store.Upsert(t.Context(),
		domain.Runner{Name: "r1", Address: fakeRunner.URL, Slots: 2}); err != nil {
		t.Fatal(err)
	}

	svc := &InstanceService{
		Instances: store, Runners: store, Client: &runnerapi.Client{},
		RunnersAlive: 30 * time.Second,
	}
	stream, err := svc.Chat(t.Context(), instID, userID, "hello")
	if err != nil {
		t.Fatal(err)
	}
	defer stream.Close()
	body, err := io.ReadAll(stream)
	if err != nil {
		t.Fatal(err)
	}
	if want := "data: {\"kind\":\"token\",\"text\":\"hi\"}\n\ndata: {\"kind\":\"done\"}\n\n"; string(body) != want {
		t.Errorf("stream: %q", body)
	}
	if raised.Load() != 1 {
		t.Errorf("raise calls: %d", raised.Load())
	}
	var status string
	var runnerID *int64
	if err := db.QueryRow(t.Context(),
		`SELECT status, runner_id FROM hub.agent_instances WHERE id = $1`, instID).Scan(&status, &runnerID); err != nil {
		t.Fatal(err)
	}
	if status != "running" || runnerID == nil {
		t.Errorf("instance after chat: status=%s runnerId=%v", status, runnerID)
	}

	// второй чат — Экземпляр уже running: raise не повторяется
	stream2, err := svc.Chat(t.Context(), instID, userID, "again")
	if err != nil {
		t.Fatal(err)
	}
	io.Copy(io.Discard, stream2)
	stream2.Close()
	if raised.Load() != 1 {
		t.Errorf("raise after second chat: %d", raised.Load())
	}

	// stop опускает через раннер и метит down в БД
	if err := svc.Stop(t.Context(), instID, userID); err != nil {
		t.Fatal(err)
	}
	if stopped.Load() != 1 {
		t.Errorf("stop calls: %d", stopped.Load())
	}
	if err := db.QueryRow(t.Context(),
		`SELECT status FROM hub.agent_instances WHERE id = $1`, instID).Scan(&status); err != nil {
		t.Fatal(err)
	}
	if status != "down" {
		t.Errorf("after stop: %s", status)
	}
}

// Раннер ставит чат в очередь: первый кадр приходит с задержкой —
// прокси ждёт (щедрый first-byte таймаут) и отдаёт поток целиком.
func TestChatWaitsForDelayedFirstFrame(t *testing.T) {
	db := testdb.Setup(t)
	userID, instID := seedInstance(t, db)

	fakeRunner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case fmt.Sprintf("/instances/%d/raise", instID):
			w.WriteHeader(http.StatusOK)
		case fmt.Sprintf("/instances/%d/chat", instID):
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(http.StatusOK)
			w.(http.Flusher).Flush()
			time.Sleep(500 * time.Millisecond) // очередь на раннере
			fmt.Fprint(w, "data: {\"kind\":\"token\",\"text\":\"late\"}\n\ndata: {\"kind\":\"done\"}\n\n")
		}
	}))
	defer fakeRunner.Close()

	store := &pgstore.Store{Pool: db}
	if _, err := store.Upsert(t.Context(),
		domain.Runner{Name: "r1", Address: fakeRunner.URL, Slots: 1}); err != nil {
		t.Fatal(err)
	}
	svc := &InstanceService{
		Instances: store, Runners: store,
		Client:       &runnerapi.Client{FirstByteTimeout: 5 * time.Second},
		RunnersAlive: 30 * time.Second,
	}
	stream, err := svc.Chat(t.Context(), instID, userID, "hi")
	if err != nil {
		t.Fatal(err)
	}
	defer stream.Close()
	body, _ := io.ReadAll(stream)
	if !strings.Contains(string(body), `"late"`) || !strings.Contains(string(body), `"done"`) {
		t.Errorf("stream: %q", body)
	}
}

// Первый кадр не пришёл за таймаут — честный domain.ErrTimeout (504), не вечное ожидание.
func TestChatFirstByteTimeout(t *testing.T) {
	db := testdb.Setup(t)
	userID, instID := seedInstance(t, db)

	fakeRunner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case fmt.Sprintf("/instances/%d/raise", instID):
			w.WriteHeader(http.StatusOK)
		case fmt.Sprintf("/instances/%d/chat", instID):
			time.Sleep(2 * time.Second) // раннер молчит дольше таймаута
		}
	}))
	defer fakeRunner.Close()

	store := &pgstore.Store{Pool: db}
	if _, err := store.Upsert(t.Context(),
		domain.Runner{Name: "r1", Address: fakeRunner.URL, Slots: 1}); err != nil {
		t.Fatal(err)
	}
	svc := &InstanceService{
		Instances: store, Runners: store,
		Client:       &runnerapi.Client{FirstByteTimeout: 200 * time.Millisecond},
		RunnersAlive: 30 * time.Second,
	}
	_, err := svc.Chat(t.Context(), instID, userID, "hi")
	if !errors.Is(err, domain.ErrTimeout) {
		t.Fatalf("want ErrTimeout, got %v", err)
	}
}

// Нет живого Раннера — ErrConflict, Экземпляр остаётся down.
func TestChatNoFreeRunner(t *testing.T) {
	db := testdb.Setup(t)
	userID, instID := seedInstance(t, db)
	store := &pgstore.Store{Pool: db}
	svc := &InstanceService{
		Instances: store, Runners: store, Client: &runnerapi.Client{},
		RunnersAlive: 30 * time.Second,
	}
	if _, err := svc.Chat(t.Context(), instID, userID, "hello"); err == nil {
		t.Fatal("expected error without runners")
	}
}
