package httpapi

import "net/http"

// NewMux собирает HTTP-поверхность hub из готовых хендлеров.
func NewMux(webhook *WebhookHandler, runners *RunnersHandler) *http.ServeMux {
	mux := http.NewServeMux()
	mux.Handle("POST /hooks/{provider}/{repositoryId}", webhook)
	mux.HandleFunc("POST /api/runners", runners.Auth(runners.Register))
	mux.HandleFunc("POST /api/runners/{id}/heartbeat", runners.Auth(runners.Heartbeat))
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	return mux
}
