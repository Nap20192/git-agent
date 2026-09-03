package domain

import (
	"context"
	"io"
	"time"
)

// RepositoryStore — чтение подключённых Репозиториев.
type RepositoryStore interface {
	// Find возвращает nil, nil если Репозиторий не подключён.
	Find(ctx context.Context, id int64, provider string) (*Repository, error)
}

// EventIngestor — приём События в одной транзакции: журнал events (дедуп по
// provider+delivery_id) + веер (тикет 011): upsert Экземпляра каждой Сборки
// из buildIDs + строка outbox на каждый Экземпляр (в сообщении instanceId).
type EventIngestor interface {
	// Ingest возвращает duplicate=true для повторной доставки (no-op) либо
	// id затронутых Экземпляров.
	Ingest(ctx context.Context, repo *Repository, e Event, payload []byte, buildIDs []int64) (duplicate bool, instanceIDs []int64, err error)
}

// SubscriptionStore — подписки Сборок (тикет 011).
type SubscriptionStore interface {
	SubscriptionsByRepo(ctx context.Context, repositoryID int64) ([]BuildSubscription, error)
	// UpsertSubscription — по unique (build, repo); обновляет actions/ref_mask.
	UpsertSubscription(ctx context.Context, s *BuildSubscription) (int64, error)
	DeleteSubscription(ctx context.Context, id, userID int64) error
	// DefaultBuild — дефолтная Сборка пользователя (фолбэк для репо без
	// подписок); nil — не задана.
	DefaultBuild(ctx context.Context, userID int64) (*AgentBuild, error)
}

// OutboxMessage — неопубликованная строка hub.outbox.
type OutboxMessage struct {
	ID         int64
	RoutingKey string
	Payload    []byte
}

// OutboxStore — очередь transactional outbox.
type OutboxStore interface {
	Unpublished(ctx context.Context, limit int) ([]OutboxMessage, error)
	MarkPublished(ctx context.Context, id int64) error
}

// EventPublisher — публикация События в брокер; возврат без ошибки означает,
// что брокер подтвердил приём (publisher confirm) — контракт outbox, тикет 005.
type EventPublisher interface {
	Publish(ctx context.Context, routingKey string, payload []byte) error
}

// Runner — регистрация Раннера (тикет 004).
type Runner struct {
	ID              int64
	Name            string
	Address         string
	Slots           int
	LastHeartbeatAt time.Time
}

// RunnerStore — реестр Раннеров.
type RunnerStore interface {
	// Upsert по уникальному имени; повторная регистрация обновляет адрес/слоты.
	Upsert(ctx context.Context, r Runner) (int64, error)
	// Heartbeat возвращает false для неизвестного Раннера.
	Heartbeat(ctx context.Context, id int64) (bool, error)
	Runners(ctx context.Context) ([]Runner, error)
	Runner(ctx context.Context, id int64) (*Runner, error)
	// AliveRunner — живой (heartbeat свежее aliveWithin) Раннер; слоты не
	// фильтруются — занятый раннер сам ставит запросы в очередь. nil — живых нет.
	AliveRunner(ctx context.Context, aliveWithin time.Duration) (*Runner, error)
}

// IdentityStore — OAuth-связки пользователя.
type IdentityStore interface {
	Identities(ctx context.Context, userID int64) ([]Identity, error)
	Identity(ctx context.Context, id, userID int64) (*Identity, error)
	// DeleteIdentity — ErrConflict, если на связку ссылаются Репозитории.
	DeleteIdentity(ctx context.Context, id, userID int64) error
}

// RepositoryAdmin — управление подключёнными Репозиториями.
type RepositoryAdmin interface {
	Repositories(ctx context.Context, userID int64) ([]Repository, error)
	Repository(ctx context.Context, id, userID int64) (*Repository, error)
	CreateRepository(ctx context.Context, r *Repository) (int64, error)
	// SetWebhook сохраняет id хука у провайдера после его создания.
	SetWebhook(ctx context.Context, id int64, providerHookID string) error
	DeleteRepository(ctx context.Context, id int64) error
	Events(ctx context.Context, repoID int64, limit int) ([]EventRecord, error)
}

// BuildStore — Сборки Агентов.
type BuildStore interface {
	Builds(ctx context.Context, userID int64) ([]AgentBuild, error)
	CreateBuild(ctx context.Context, b *AgentBuild) (int64, error)
	UpdateBuild(ctx context.Context, b *AgentBuild) error
	DeleteBuild(ctx context.Context, id, userID int64) error
}

// ConnectionStore — LLM/sandbox-подключения.
type ConnectionStore interface {
	LlmConnections(ctx context.Context, userID int64) ([]LlmConnection, error)
	CreateLlmConnection(ctx context.Context, c *LlmConnection) (int64, error)
	DeleteLlmConnection(ctx context.Context, id, userID int64) error
	SandboxConnections(ctx context.Context) ([]SandboxConnection, error)
	// SandboxConnection — nil, nil для незнакомого id.
	SandboxConnection(ctx context.Context, id int64) (*SandboxConnection, error)
	CreateSandboxConnection(ctx context.Context, c *SandboxConnection) (int64, error)
	DeleteSandboxConnection(ctx context.Context, id int64) error
}

// SandboxInstanceStore — Экземпляры Сэндбоксов (владение — hub/юзер, не раннер).
type SandboxInstanceStore interface {
	SandboxInstances(ctx context.Context) ([]SandboxInstance, error)
	SandboxInstance(ctx context.Context, id int64) (*SandboxInstance, error)
	CreateSandboxInstance(ctx context.Context, externalID string, connectionID int64) (int64, error)
	MarkSandboxInstanceDead(ctx context.Context, id int64) error
	// LinkInstanceSandbox — привязать Экземпляр Агента юзера к песочнице.
	LinkInstanceSandbox(ctx context.Context, instanceID, sandboxInstanceID, userID int64) error
}

// SandboxLifecycle — lifecycle-API OpenSandbox (create no-TTL / destroy) по
// координатам sandbox-подключения. Раннер этим НЕ пользуется.
type SandboxLifecycle interface {
	CreateSandbox(ctx context.Context, domain, apiKey, image string) (externalID string, err error)
	DeleteSandbox(ctx context.Context, domain, apiKey, externalID string) error
}

// InstanceStore — Экземпляры Агентов и их результаты.
type InstanceStore interface {
	Instances(ctx context.Context, userID int64, repositoryID *int64) ([]AgentInstance, error)
	Instance(ctx context.Context, id, userID int64) (*AgentInstance, error)
	Reports(ctx context.Context, instanceID int64) ([]Report, error)
	Findings(ctx context.Context, instanceID int64) ([]Finding, error)
	SetInstanceRunning(ctx context.Context, id, runnerID int64) error
	SetInstanceDown(ctx context.Context, id int64) error
	// Activity — реплей activity-кадров хода из hub.activity (payload jsonb
	// как есть, порядок seq); eventID nil = последний ход Экземпляра.
	Activity(ctx context.Context, instanceID int64, eventID *int64) ([][]byte, error)
	// RequeueInstance — «Продолжить»: незавершённые События Экземпляра — снова
	// в outbox (механика heartbeat-ре-публикации); возвращает eventId, пусто =
	// нечего продолжать.
	RequeueInstance(ctx context.Context, instanceID int64) ([]int64, error)
}

// StaleRequeuer — надзор за протухшими Раннерами (тикеты 004/005):
// их running-Экземпляры → down, необработанные События → снова в outbox.
type StaleRequeuer interface {
	// RequeueStale возвращает сколько Экземпляров опущено и trace_id
	// переопубликованных Событий (по одному на строку outbox).
	RequeueStale(ctx context.Context, timeout time.Duration) (downed int, requeued []string, err error)
}

// OAuthClient — OAuth-флоу провайдера (тикет 003). Провайдер без ключей
// в конфиге — ErrUnavailable, сервис при этом работает.
type OAuthClient interface {
	AuthURL(provider, redirectURI, state string) (string, error)
	Exchange(ctx context.Context, provider, code, redirectURI string) (*OAuthToken, error)
	Refresh(ctx context.Context, provider, refreshToken string) (*OAuthToken, error)
	// UserInfo — профиль владельца токена: (provider_user_id, username).
	UserInfo(ctx context.Context, provider, accessToken string) (providerUserID, username string, err error)
}

// AuthStore — пользователи, связки и сессии (тикет 003).
type AuthStore interface {
	CreateUser(ctx context.Context, displayName string) (int64, error)
	UserDisplayName(ctx context.Context, id int64) (string, error)
	FindIdentityByProviderUser(ctx context.Context, provider, providerUserID string) (*Identity, error)
	InsertIdentity(ctx context.Context, i *Identity) (int64, error)
	UpdateIdentityTokens(ctx context.Context, id int64, username string, accessEnc, refreshEnc []byte, expiresAt *time.Time) error
	// CreateSession — opaque-токен в httpOnly cookie.
	CreateSession(ctx context.Context, token string, userID int64, expiresAt time.Time) error
	// SessionUser — false для незнакомого или истёкшего токена.
	SessionUser(ctx context.Context, token string) (int64, bool, error)
	DeleteSession(ctx context.Context, token string) error
}

// ProviderClient — API провайдера (GitHub/GitLab) от имени связки.
type ProviderClient interface {
	Repos(ctx context.Context, provider, token string) ([]ProviderRepo, error)
	Repo(ctx context.Context, provider, token, externalID string) (*ProviderRepo, error)
	// RepoByPath — репо по owner/name; пустой token — публичный API без авторизации (тикет 015).
	RepoByPath(ctx context.Context, provider, token, owner, name string) (*ProviderRepo, error)
	// CreateHook вешает вебхук на все действия; возвращает id хука у провайдера.
	CreateHook(ctx context.Context, provider, token string, repo ProviderRepo, url, secret string) (string, error)
	DeleteHook(ctx context.Context, provider, token string, repo *Repository, hookID string) error
	// BranchHead — sha HEAD-коммита ветки/тега (ручной запуск); пустой token — публичный API.
	BranchHead(ctx context.Context, provider, token string, repo *Repository, ref string) (string, error)
}

// RunnerClient — API Раннера (тикет 004): поднять/опустить Экземпляр, чат, терминал.
type RunnerClient interface {
	// Raise отвечает быстро: queued=true — слоты заняты, раннер поднимет
	// Экземпляр фоном, когда слот освободится (202 от раннера).
	Raise(ctx context.Context, addr string, instanceID int64) (queued bool, err error)
	Stop(ctx context.Context, addr string, instanceID int64) error
	// Chat возвращает SSE-поток раннера (кадры ChatEvent); закрывает вызывающий.
	Chat(ctx context.Context, addr string, instanceID int64, message string) (io.ReadCloser, error)
	// Terminal — SSE-поток стрим-консоли (кадры TerminalEvent); закрывает вызывающий.
	Terminal(ctx context.Context, addr string, instanceID int64, command string) (io.ReadCloser, error)
	// Activity — SSE-поток activity-кадров хода (кадры ActivityEvent, тикет 012);
	// eventID nil = живой либо последний ход. Закрывает вызывающий.
	Activity(ctx context.Context, addr string, instanceID int64, eventID *int64) (io.ReadCloser, error)
}
