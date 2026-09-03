package domain

import (
	"encoding/json"
	"time"
)

// Identity — OAuth-связка пользователя (тикет 003).
type Identity struct {
	ID              int64
	UserID          int64
	Provider        string
	ProviderUserID  string
	Username        string
	AccessTokenEnc  []byte
	RefreshTokenEnc []byte // nullable; refresh-флоу по 401 (GitLab)
	TokenExpiresAt  *time.Time
	CreatedAt       time.Time
}

// OAuthToken — результат обмена кода/refresh у провайдера.
type OAuthToken struct {
	AccessToken  string
	RefreshToken string // пустой у GitHub OAuth App (токены вечные)
	ExpiresAt    *time.Time
}

// ProviderRepo — репозиторий, видимый связке через API провайдера.
type ProviderRepo struct {
	ExternalID    string
	Owner         string
	Name          string
	DefaultBranch *string
	Private       bool
}

// EventRecord — строка журнала hub.events.
type EventRecord struct {
	ID         int64
	Provider   string
	Action     string
	CommitSHA  *string
	Ref        *string
	ReceivedAt time.Time
	TraceID    string
	// diff-контекст (миграция 006), nil = неизвестно
	BeforeSHA    *string
	BaseSHA      *string
	HeadSHA      *string
	PRNumber     *int
	PRTitle      *string
	PRBody       *string
	ChangedFiles json.RawMessage // JSON-массив путей либо nil
}

// AgentBuild — Сборка Агента (CONTEXT.md): хранимое определение, не процесс.
type AgentBuild struct {
	ID                  int64
	UserID              int64
	Name                string
	LlmConnectionID     int64
	SandboxConnectionID int64
	Prompt              *string
	MemoryPreset        *string
	Limits              []byte // JSONB как есть
	IsDefault           bool
	CreatedAt           time.Time
}

type LlmConnection struct {
	ID        int64
	UserID    int64
	Name      string
	APIBase   string
	APIKeyEnc []byte
	Model     string
	CreatedAt time.Time
}

type SandboxConnection struct {
	ID        int64
	Name      string
	Domain    string
	APIKeyEnc []byte // nullable
	Image     *string
	CreatedAt time.Time
}

// SandboxInstance — Экземпляр Сэндбокса (CONTEXT.md): реально провиженная
// песочница (no-TTL). Создаёт/убивает hub по команде юзера; раннер только
// подключается по external_id.
type SandboxInstance struct {
	ID                  int64
	ExternalID          string
	SandboxConnectionID int64
	Status              string // alive | dead
	CreatedAt           time.Time
	KilledAt            *time.Time
}

// AgentInstance — Экземпляр Агента (CONTEXT.md): долгоживущий агент Репозитория.
type AgentInstance struct {
	ID                int64
	BuildID           int64
	RepositoryID      int64
	SandboxInstanceID *int64
	SandboxExternalID *string // derived: привязанный Экземпляр Сэндбокса
	SandboxStatus     *string
	ThreadID          string
	Status            string // down | running
	RunnerID          *int64
	UpdatedAt         time.Time
}

type Report struct {
	ID         int64
	InstanceID int64
	EventID    *int64
	Summary    string
	CreatedAt  time.Time
}

type Finding struct {
	ID          int64
	InstanceID  int64
	ReportID    *int64
	Severity    string
	CWE         *string
	CVE         *string
	File        *string
	LineStart   *int
	LineEnd     *int
	Evidence    *string
	Remediation *string
	CreatedAt   time.Time
}
