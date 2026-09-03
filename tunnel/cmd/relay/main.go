// Command relay — вечный публичный вход для вебхуков (Railway).
// POST /hooks/* складывается в очередь в памяти, GET /pull забирает
// длинным поллингом (at-most-once: потерянное redeliver'ится из UI провайдера).
package main

import (
	"crypto/subtle"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"sync"
	"time"
)

const (
	maxQueue = 1000
	maxBody  = 10 << 20 // зеркалит лимит hub
	maxWait  = 55 * time.Second
)

type record struct {
	Path       string      `json:"path"`
	Headers    http.Header `json:"headers"`
	Body       []byte      `json:"body"`
	ReceivedAt time.Time   `json:"receivedAt"`
}

type queue struct {
	mu     sync.Mutex
	recs   []record
	notify chan struct{}
}

func newQueue() *queue { return &queue{notify: make(chan struct{}, 1)} }

func (q *queue) push(r record) {
	q.mu.Lock()
	q.recs = append(q.recs, r)
	if n := len(q.recs) - maxQueue; n > 0 {
		q.recs = q.recs[n:] // старое вытесняется
	}
	q.mu.Unlock()
	select {
	case q.notify <- struct{}{}:
	default:
	}
}

func (q *queue) drain() []record {
	q.mu.Lock()
	defer q.mu.Unlock()
	recs := q.recs
	q.recs = nil
	return recs
}

func newHandler(q *queue, token string) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /hooks/", func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(io.LimitReader(r.Body, maxBody))
		if err != nil {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		q.push(record{Path: r.URL.Path, Headers: r.Header.Clone(), Body: body, ReceivedAt: time.Now().UTC()})
	})
	mux.HandleFunc("GET /pull", func(w http.ResponseWriter, r *http.Request) {
		got := []byte(r.Header.Get("X-Relay-Token"))
		if subtle.ConstantTimeCompare(got, []byte(token)) != 1 {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		wait, _ := time.ParseDuration(r.URL.Query().Get("wait"))
		if wait > maxWait {
			wait = maxWait
		}
		recs := q.drain()
		if len(recs) == 0 && wait > 0 {
			timer := time.NewTimer(wait)
			defer timer.Stop()
			select {
			case <-q.notify:
				recs = q.drain()
			case <-timer.C:
			case <-r.Context().Done():
				return
			}
		}
		if recs == nil {
			recs = []record{}
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(recs)
	})
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "ok")
	})
	return mux
}

func main() {
	token := os.Getenv("RELAY_TOKEN")
	if token == "" {
		log.Fatal("relay: RELAY_TOKEN is required")
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("relay: listening on :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, newHandler(newQueue(), token)))
}
