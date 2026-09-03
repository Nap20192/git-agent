/**
 * Wire types for the Go hub backend. Source of truth: backend/docs/openapi.yaml
 * (authoritative, camelCase). Ids are numeric; keys only ever arrive masked.
 */

export type Provider = "github" | "gitlab";

export interface Identity {
  id: number;
  provider: Provider;
  username: string;
  createdAt?: string;
}

export interface Me {
  id: number;
  displayName: string;
  identities: Identity[];
}

/** A repo visible to an identity on the provider side (not yet connected). */
export interface ProviderRepo {
  externalId: string;
  owner: string;
  name: string;
  defaultBranch?: string | null;
  private?: boolean;
}

/** A connected repository (webhook installed by the hub). */
export interface Repository {
  id: number;
  identityId: number;
  provider: Provider;
  externalId: string;
  owner: string;
  name: string;
  defaultBranch?: string | null;
  buildId?: number | null;
  connectedAt: string;
}

/** Событие — a thin webhook fact in the repository journal. */
export interface RepoEvent {
  id: number;
  provider: string;
  action: string;
  commitSha?: string | null;
  ref?: string | null;
  receivedAt: string;
  /** Сквозной trace_id запроса, породившего Событие (32 hex); "" до миграции 004. */
  traceId?: string;
}

/** Сборка Агента — stored agent definition, not a live process. */
export interface AgentBuildInput {
  name: string;
  llmConnectionId?: number;
  sandboxConnectionId?: number;
  prompt?: string | null;
  memoryPreset?: string | null;
  limits?: Record<string, unknown>;
  isDefault?: boolean;
}

export interface AgentBuild extends AgentBuildInput {
  id: number;
  createdAt?: string;
}

export interface LlmConnection {
  id: number;
  name: string;
  apiBase: string;
  /** Redaction invariant: only the mask ever crosses the wire. */
  apiKeyMasked: string;
  model: string;
}

export interface SandboxConnection {
  id: number;
  name: string;
  domain: string;
  apiKeyMasked?: string | null;
  image?: string | null;
}

export type InstanceStatus = "down" | "running";

/**
 * Экземпляр Сэндбокса — a really-provisioned sandbox (no-TTL). Created and
 * killed by the hub on the user's command; the runner only connects by
 * externalId and never manages the lifecycle.
 */
export interface SandboxInstance {
  id: number;
  externalId: string;
  sandboxConnectionId: number;
  status: "alive" | "dead";
  createdAt?: string;
  killedAt?: string | null;
}

/** Экземпляр Агента — the long-lived per-repository agent. */
export interface AgentInstance {
  id: number;
  buildId: number;
  repositoryId: number;
  sandboxInstanceId?: number | null;
  /** Derived from the linked Экземпляр Сэндбокса. */
  sandboxExternalId?: string | null;
  sandboxStatus?: "alive" | "dead" | null;
  threadId?: string;
  status: InstanceStatus;
  runnerId?: number | null;
  updatedAt?: string;
}

/**
 * 202 body of POST /api/repositories/{id}/trigger — manual agent run, same
 * path as a webhook push (backend/docs/openapi.yaml). `duplicate` — this
 * commit was already triggered in this mode (manual only; full is never a dup).
 */
export interface TriggerResult {
  commitSha: string;
  duplicate: boolean;
  instanceIds: number[];
}

/** Раннер — a worker host that raises Экземпляры (slots = capacity). */
export interface Runner {
  id: number;
  name: string;
  address: string;
  slots: number;
  lastHeartbeatAt?: string;
}

export interface Report {
  id: number;
  instanceId: number;
  eventId?: number | null;
  summary: string;
  createdAt: string;
}

export interface Finding {
  id: number;
  instanceId: number;
  reportId?: number | null;
  severity: string;
  cwe?: string | null;
  cve?: string | null;
  file?: string | null;
  lineStart?: number | null;
  lineEnd?: number | null;
  evidence?: string | null;
  remediation?: string | null;
  createdAt?: string;
}

/**
 * One SSE frame of POST /api/instances/{id}/chat. Fixed in the backend
 * contract (openapi.yaml, schema ChatEvent): kind=token — a reply fragment,
 * kind=activity — a status line, kind=done — terminal frame, stream closes.
 */
export interface ChatEvent {
  kind: "token" | "activity" | "done";
  text?: string | null;
}

/**
 * One SSE frame of POST /api/instances/{id}/terminal (openapi.yaml,
 * TerminalEvent). kind=output — command output (stdout+stderr merged);
 * kind=exit — command finished (code/cwd null when the shell never reached
 * the marker); kind=done — terminal frame, stream closes.
 */
export interface TerminalEvent {
  kind: "output" | "exit" | "done";
  text?: string | null;
  code?: number | null;
  cwd?: string | null;
}

/** Subagent state as painted by the run graph (ticket 012). */
export type ActivityStatus = "queued" | "working" | "done" | "failed" | "timeout";

/**
 * One SSE frame of GET /api/instances/{id}/activity (openapi.yaml,
 * ActivityEvent) — the run-graph feed «Лид → Сабагенты» of one ход.
 * run_started/run_finished/run_failed — turn boundaries; node — a lead node
 * finished (description = node name); task_started — a Сабагент
 * (status queued → working); task_finished/task_failed — its terminal state
 * (description = error, findingsCount = its Находки); task_report — the
 * Сабагент's self-report text (description); done — stream closes.
 * Work-log kinds (tool_call / tool_result / text, see activity.ts) are a
 * proposed extension outside the contract: folded if present, never sent yet.
 */
export interface ActivityEvent {
  kind:
    | "run_started"
    | "node"
    | "task_started"
    | "task_finished"
    | "task_failed"
    | "task_report"
    | "run_finished"
    | "run_failed"
    | "done";
  taskId?: string | null;
  description?: string | null;
  status?: ActivityStatus | null;
  findingsCount?: number | null;
  ts?: string | null;
  /** Сквозной trace_id хода — тот же, что в логах hub/раннера и в Langfuse/LangSmith. */
  traceId?: string | null;
}

/**
 * Подписка Сборки на События Репозитория (ticket 011). Empty actions = all
 * actions; null refMask = any ref (mask is a glob over the short ref, e.g.
 * "release/*"). A repo with no subscriptions is served by the default Сборка.
 * Mirrors the wt/backend DTO; re-check once its openapi.yaml commit lands.
 */
export interface Subscription {
  id: number;
  buildId: number;
  repositoryId: number;
  actions: string[];
  refMask?: string | null;
  createdAt?: string;
}
