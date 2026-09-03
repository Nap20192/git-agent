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

// Терминал connect-only: down-Экземпляр — 409 без raise; running —
// SSE-поток раннера проксируется как есть.
func TestTerminalRequiresRunningInstance(t *testing.T) {
	db := testdb.Setup(t)
	userID, instID := seedInstance(t, db)

	var raised atomic.Int64
	fakeRunner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case fmt.Sprintf("/instances/%d/raise", instID):
			raised.Add(1)
			w.WriteHeader(http.StatusOK)
		case fmt.Sprintf("/instances/%d/terminal", instID):
			w.Header().Set("Content-Type", "text/event-stream")
			fmt.Fprint(w, "data: {\"kind\":\"output\",\"text\":\"file.txt\"}\n\n")
			fmt.Fprint(w, "data: {\"kind\":\"exit\",\"code\":0,\"cwd\":\"/repo\"}\n\n")
			fmt.Fprint(w, "data: {\"kind\":\"done\"}\n\n")
		default:
			t.Errorf("unexpected runner call: %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer fakeRunner.Close()

	store := &pgstore.Store{Pool: db}
	runnerID, err := store.Upsert(t.Context(),
		domain.Runner{Name: "r1", Address: fakeRunner.URL, Slots: 2})
	if err != nil {
		t.Fatal(err)
	}
	svc := &InstanceService{
		Instances: store, Runners: store, Client: &runnerapi.Client{},
		RunnersAlive: 30 * time.Second,
	}

	// down: терминал не поднимает Экземпляр и не трогает раннер
	if _, err := svc.Terminal(t.Context(), instID, userID, "ls"); !errors.Is(err, domain.ErrConflict) {
		t.Fatalf("want ErrConflict for down instance, got %v", err)
	}
	if raised.Load() != 0 {
		t.Errorf("terminal must not raise, raise calls: %d", raised.Load())
	}

	// running: прокси потока
	if err := store.SetInstanceRunning(t.Context(), instID, runnerID); err != nil {
		t.Fatal(err)
	}
	stream, err := svc.Terminal(t.Context(), instID, userID, "ls")
	if err != nil {
		t.Fatal(err)
	}
	defer stream.Close()
	body, err := io.ReadAll(stream)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(body), "\"kind\":\"exit\"") || !strings.Contains(string(body), "\"kind\":\"done\"") {
		t.Errorf("stream: %q", body)
	}
}

// down-Экземпляр: hub реплеит activity-кадры из hub.activity сам, без раннера;
// eventId выбирает ход, без него — последний (включая NULL-группу чата).
func TestActivityReplayForDownInstance(t *testing.T) {
	db := testdb.Setup(t)
	userID, instID := seedInstance(t, db)

	var eventID int64
	if err := db.QueryRow(t.Context(), `
		INSERT INTO hub.events (provider, delivery_id, repository_id, action, payload)
		SELECT 'github', 'd-1', repository_id, 'push', '{}' FROM hub.agent_instances WHERE id = $1
		RETURNING id`, instID).Scan(&eventID); err != nil {
		t.Fatal(err)
	}
	for seq, frame := range []string{
		`{"kind": "run_started", "ts": "2026-01-01T00:00:00Z"}`,
		`{"kind": "run_finished", "findingsCount": 1, "ts": "2026-01-01T00:01:00Z"}`,
	} {
		if _, err := db.Exec(t.Context(), `
			INSERT INTO hub.activity (instance_id, event_id, seq, kind, payload)
			VALUES ($1, $2, $3, 'x', $4)`, instID, eventID, seq+1, frame); err != nil {
			t.Fatal(err)
		}
	}
	// более поздний ход чата (event_id NULL) — он и есть «последний»
	if _, err := db.Exec(t.Context(), `
		INSERT INTO hub.activity (instance_id, event_id, seq, kind, payload)
		VALUES ($1, NULL, 1, 'x', '{"kind": "run_started", "chat": true}')`, instID); err != nil {
		t.Fatal(err)
	}

	svc := &InstanceService{
		Instances: store(db), Runners: store(db), Client: &runnerapi.Client{},
		RunnersAlive: 30 * time.Second,
	}

	read := func(eventID *int64) string {
		t.Helper()
		stream, err := svc.Activity(t.Context(), instID, userID, eventID)
		if err != nil {
			t.Fatal(err)
		}
		defer stream.Close()
		body, err := io.ReadAll(stream)
		if err != nil {
			t.Fatal(err)
		}
		return string(body)
	}

	byEvent := read(&eventID)
	if !strings.Contains(byEvent, `"run_started"`) || !strings.Contains(byEvent, `"findingsCount": 1`) ||
		!strings.HasSuffix(byEvent, "data: {\"kind\": \"done\"}\n\n") {
		t.Errorf("event replay: %q", byEvent)
	}
	latest := read(nil)
	if !strings.Contains(latest, `"chat": true`) || strings.Contains(latest, "findingsCount") {
		t.Errorf("latest turn must be the chat one: %q", latest)
	}
}

func store(db *pgxpool.Pool) *pgstore.Store { return &pgstore.Store{Pool: db} }
