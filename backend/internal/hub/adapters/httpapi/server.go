package httpapi

import (
	"net/http"

	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

type Store interface {
	domain.AuthStore
	domain.IdentityStore
	domain.RepositoryAdmin
	domain.SubscriptionStore
	domain.BuildStore
	domain.ConnectionStore
	domain.InstanceStore
	domain.SandboxInstanceStore
	domain.RunnerStore
}

type Server struct {
	Store Store

	Auth         *app.AuthService
	Repositories *app.RepositoryService
	Instances    *app.InstanceService
	Webhook      *app.WebhookService
	Sandboxes    *app.SandboxService
	Connections  *app.ConnectionService

	Defaults      domain.Defaults // чем заполнять пустые поля при создании (config.Defaults)
	DevUserID     int64
	RunnerToken   string // X-Runner-Token раннеров (RUNNER_TOKEN)
	FrontendURL   string // redirect после OAuth-callback
	PublicBaseURL string
}

func NewMux(s *Server) *http.ServeMux {
	mux := http.NewServeMux()
	open := handle
	user := func(fn handler) http.HandlerFunc { return s.session(handle(fn)) }
	runner := func(fn handler) http.HandlerFunc { return s.runnerAuth(handle(fn)) }

	mux.HandleFunc("POST /hooks/{provider}/{repositoryId}", s.webhook)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })

	mux.HandleFunc("GET /api/auth/{provider}/login", open(s.login))
	mux.HandleFunc("GET /api/auth/{provider}/callback", open(s.callback))
	mux.HandleFunc("POST /api/auth/logout", open(s.logout))
	mux.HandleFunc("GET /api/me", user(s.me))

	mux.HandleFunc("GET /api/identities", user(s.listIdentities))
	mux.HandleFunc("DELETE /api/identities/{id}", user(s.deleteIdentity))
	mux.HandleFunc("GET /api/identities/{id}/repos", user(s.identityRepos))

	mux.HandleFunc("GET /api/repositories", user(s.listRepositories))
	mux.HandleFunc("POST /api/repositories", user(s.connectRepository))
	mux.HandleFunc("PATCH /api/repositories/{id}", user(s.patchRepository))
	mux.HandleFunc("DELETE /api/repositories/{id}", user(s.disconnectRepository))
	mux.HandleFunc("GET /api/repositories/{id}/events", user(s.repositoryEvents))
	mux.HandleFunc("GET /api/repositories/{id}/findings", user(s.repositoryFindings))
	mux.HandleFunc("GET /api/repositories/{id}/findings/export", user(s.exportRepositoryFindings))
	mux.HandleFunc("POST /api/repositories/{id}/trigger", user(s.triggerRepository))
	mux.HandleFunc("POST /api/repositories/{id}/raise", user(s.raiseRepository))
	mux.HandleFunc("GET /api/repositories/{id}/reports", user(s.repositoryReports))
	mux.HandleFunc("GET /api/repositories/{id}/subscriptions", user(s.listSubscriptions))
	mux.HandleFunc("POST /api/repositories/{id}/subscriptions", user(s.createSubscription))
	mux.HandleFunc("DELETE /api/subscriptions/{id}", user(s.deleteSubscription))

	mux.HandleFunc("GET /api/builds", user(s.listBuilds))
	mux.HandleFunc("POST /api/builds", user(s.createBuild))
	mux.HandleFunc("PATCH /api/builds/{id}", user(s.patchBuild))
	mux.HandleFunc("DELETE /api/builds/{id}", user(s.deleteBuild))

	mux.HandleFunc("GET /api/connections/llm", user(s.listLlmConnections))
	mux.HandleFunc("GET /api/defaults", user(s.getDefaults))
	mux.HandleFunc("POST /api/connections/llm", user(s.createLlmConnection))
	mux.HandleFunc("PUT /api/connections/llm/{id}", user(s.updateLlmConnection))
	mux.HandleFunc("DELETE /api/connections/llm/{id}", user(s.deleteLlmConnection))
	mux.HandleFunc("GET /api/connections/sandbox", user(s.listSandboxConnections))
	mux.HandleFunc("POST /api/connections/sandbox", user(s.createSandboxConnection))
	mux.HandleFunc("DELETE /api/connections/sandbox/{id}", user(s.deleteSandboxConnection))

	mux.HandleFunc("GET /api/sandbox-instances", user(s.listSandboxInstances))
	mux.HandleFunc("POST /api/sandbox-instances", user(s.createSandboxInstance))
	mux.HandleFunc("DELETE /api/sandbox-instances/{id}", user(s.killSandboxInstance))
	mux.HandleFunc("POST /api/instances/{id}/sandbox", user(s.linkInstanceSandbox))

	mux.HandleFunc("GET /api/instances", user(s.listInstances))
	mux.HandleFunc("GET /api/instances/{id}", user(s.getInstance))
	mux.HandleFunc("GET /api/instances/{id}/reports", user(s.instanceReports))
	mux.HandleFunc("GET /api/instances/{id}/messages", user(s.instanceMessages))
	mux.HandleFunc("GET /api/instances/{id}/findings", user(s.instanceFindings))
	mux.HandleFunc("GET /api/instances/{id}/findings/export", user(s.exportInstanceFindings))
	mux.HandleFunc("GET /api/instances/{id}/activity", user(s.instanceActivity))
	mux.HandleFunc("POST /api/instances/{id}/stop", user(s.stopInstance))
	mux.HandleFunc("POST /api/instances/{id}/raise", user(s.raiseInstance))
	mux.HandleFunc("POST /api/instances/{id}/resume", user(s.resumeInstance))
	mux.HandleFunc("POST /api/instances/{id}/chat", user(s.instanceChat))
	mux.HandleFunc("POST /api/instances/{id}/terminal", user(s.instanceTerminal))

	mux.HandleFunc("GET /api/runners", user(s.listRunners))
	mux.HandleFunc("POST /api/runners", runner(s.registerRunner))
	mux.HandleFunc("POST /api/runners/{id}/heartbeat", runner(s.runnerHeartbeat))

	return mux
}
