package httpapi

import "net/http"

// Handlers — все хендлеры HTTP-поверхности hub (backend/docs/openapi.yaml).
type Handlers struct {
	Session       *Session
	Auth          *AuthHandler
	Webhook       *WebhookHandler
	Runners       *RunnersHandler
	Identities    *IdentitiesHandler
	Repositories  *RepositoriesHandler
	Subscriptions *SubscriptionsHandler
	Builds        *BuildsHandler
	Connections   *ConnectionsHandler
	Instances     *InstancesHandler
	Sandboxes     *SandboxInstancesHandler
}

// NewMux собирает HTTP-поверхность hub. Пользовательские /api/* — за
// Session (валидная cookie-сессия, иначе 401), /api/auth/* — открыты,
// раннерные — за X-Runner-Token, вебхуки — за подписью провайдера.
func NewMux(h Handlers) *http.ServeMux {
	mux := http.NewServeMux()
	s := h.Session.Wrap

	mux.Handle("POST /hooks/{provider}/{repositoryId}", h.Webhook)

	mux.HandleFunc("GET /api/auth/{provider}/login", h.Auth.Login)
	mux.HandleFunc("GET /api/auth/{provider}/callback", h.Auth.Callback)
	mux.HandleFunc("POST /api/auth/logout", h.Auth.Logout)
	mux.HandleFunc("GET /api/me", s(h.Auth.Me))

	mux.HandleFunc("POST /api/runners", h.Runners.Auth(h.Runners.Register))
	mux.HandleFunc("POST /api/runners/{id}/heartbeat", h.Runners.Auth(h.Runners.Heartbeat))
	mux.HandleFunc("GET /api/runners", s(h.Runners.List))

	mux.HandleFunc("GET /api/identities", s(h.Identities.List))
	mux.HandleFunc("DELETE /api/identities/{id}", s(h.Identities.Delete))
	mux.HandleFunc("GET /api/identities/{id}/repos", s(h.Identities.Repos))

	mux.HandleFunc("GET /api/repositories", s(h.Repositories.List))
	mux.HandleFunc("POST /api/repositories", s(h.Repositories.Connect))
	mux.HandleFunc("PATCH /api/repositories/{id}", s(h.Repositories.Patch))
	mux.HandleFunc("DELETE /api/repositories/{id}", s(h.Repositories.Disconnect))
	mux.HandleFunc("GET /api/repositories/{id}/events", s(h.Repositories.Events))
	mux.HandleFunc("POST /api/repositories/{id}/trigger", s(h.Repositories.Trigger))
	mux.HandleFunc("GET /api/repositories/{id}/subscriptions", s(h.Subscriptions.List))
	mux.HandleFunc("POST /api/repositories/{id}/subscriptions", s(h.Subscriptions.Create))
	mux.HandleFunc("DELETE /api/subscriptions/{id}", s(h.Subscriptions.Delete))

	mux.HandleFunc("GET /api/builds", s(h.Builds.List))
	mux.HandleFunc("POST /api/builds", s(h.Builds.Create))
	mux.HandleFunc("PATCH /api/builds/{id}", s(h.Builds.Patch))
	mux.HandleFunc("DELETE /api/builds/{id}", s(h.Builds.Delete))

	mux.HandleFunc("GET /api/connections/llm", s(h.Connections.ListLlm))
	mux.HandleFunc("POST /api/connections/llm", s(h.Connections.CreateLlm))
	mux.HandleFunc("DELETE /api/connections/llm/{id}", s(h.Connections.DeleteLlm))
	mux.HandleFunc("GET /api/connections/sandbox", s(h.Connections.ListSandbox))
	mux.HandleFunc("POST /api/connections/sandbox", s(h.Connections.CreateSandbox))
	mux.HandleFunc("DELETE /api/connections/sandbox/{id}", s(h.Connections.DeleteSandbox))

	mux.HandleFunc("GET /api/sandbox-instances", s(h.Sandboxes.List))
	mux.HandleFunc("POST /api/sandbox-instances", s(h.Sandboxes.Create))
	mux.HandleFunc("DELETE /api/sandbox-instances/{id}", s(h.Sandboxes.Kill))
	mux.HandleFunc("POST /api/instances/{id}/sandbox", s(h.Sandboxes.Link))

	mux.HandleFunc("GET /api/instances", s(h.Instances.List))
	mux.HandleFunc("GET /api/instances/{id}", s(h.Instances.Get))
	mux.HandleFunc("GET /api/instances/{id}/reports", s(h.Instances.Reports))
	mux.HandleFunc("GET /api/instances/{id}/findings", s(h.Instances.Findings))
	mux.HandleFunc("POST /api/instances/{id}/stop", s(h.Instances.Stop))
	mux.HandleFunc("POST /api/instances/{id}/raise", s(h.Instances.Raise))
	mux.HandleFunc("POST /api/instances/{id}/resume", s(h.Instances.Resume))
	mux.HandleFunc("POST /api/instances/{id}/chat", s(h.Instances.Chat))
	mux.HandleFunc("GET /api/instances/{id}/activity", s(h.Instances.Activity))
	mux.HandleFunc("POST /api/instances/{id}/terminal", s(h.Instances.Terminal))

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	return mux
}
