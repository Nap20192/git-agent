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

/** How a repository is connected: `hook` — own repo, hub installed a webhook;
 *  `watch` — someone else's public repo added by URL, no webhook, manual runs only. */
export type RepoMode = "hook" | "watch";

/** A connected repository. */
export interface Repository {
  id: number;
  /** null for watch repos — no identity behind them. */
  identityId: number | null;
  mode: RepoMode;
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
export interface RaiseResult {
  instances: { id: number; status: "running" | "queued" }[];
}

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

/**
 * Structured Отчёт (findings v2). Every field optional — the agent fills what
 * it knows; `summary` stays the markdown fallback.
 * TODO(findings-v2): re-check field names against backend/docs/openapi.yaml once the backend commit lands.
 */
export interface ReportStructured {
  summary?: string | null;
  scope?: {
    eventType?: string | null;
    /** HEAD commit of the reviewed scope (the Событие's commit). */
    commit?: string | null;
    /** commit range: push — {before, after}; PR — {base, head}; null for full_scan/chat. */
    range?: { before?: string | null; after?: string | null; base?: string | null; head?: string | null } | string | null;
    filesTouched?: number | string[] | null;
    linesChanged?: number | null;
  } | null;
  method?: string[] | null;
  findingsBySeverity?: Record<string, number> | null;
  topRisks?: string[] | null;
  recommendations?: string[] | null;
  limitations?: string[] | null;
}

export interface Report {
  id: number;
  instanceId: number;
  eventId?: number | null;
  summary: string;
  structured?: ReportStructured | null;
  createdAt: string;
  /** From the report's Событие; null for chat-turn reports. */
  commitSha?: string | null;
  ref?: string | null;
  action?: string | null;
}

/** Whether the Событие under review introduced the finding or it predates it. */
export type IntroducedBy = "this_event" | "earlier";

/** Находка (findings v2: title/description/impact/confidence/category/references + git blame + eventId).
 *  TODO(findings-v2): re-check against backend/docs/openapi.yaml once the backend commit lands. */
export interface Finding {
  id: number;
  instanceId: number;
  reportId?: number | null;
  eventId?: number | null;
  severity: string;
  title?: string | null;
  description?: string | null;
  impact?: string | null;
  /** "high" | "medium" | "low" (free string on the wire). */
  confidence?: string | null;
  /** e.g. injection, secrets, authz, crypto, config, deps. */
  category?: string | null;
  cwe?: string | null;
  cve?: string | null;
  file?: string | null;
  lineStart?: number | null;
  lineEnd?: number | null;
  evidence?: string | null;
  remediation?: string | null;
  references?: string[] | null;
  blameAuthor?: string | null;
  blameEmail?: string | null;
  blameCommit?: string | null;
  blameDate?: string | null;
  blameCommitMessage?: string | null;
  introducedBy?: IntroducedBy | null;
  createdAt?: string;
}

/** Query params of GET …/findings (all optional; empty = no filter). */
export interface FindingFilters {
  severity?: string;
  category?: string;
  eventId?: number;
  introducedBy?: IntroducedBy;
}
export type FindingExportFormat = "csv" | "md";

/**
 * One SSE frame of POST /api/instances/{id}/chat. Fixed in the backend
 * contract (openapi.yaml, schema ChatEvent): kind=token — a reply fragment,
 * kind=activity — a status line, kind=done — terminal frame, stream closes.
 */
export interface ChatEvent {
  /** token — a reply fragment as it is generated; message — a whole agent
   *  message (replaces the streamed text: canonical, and the fallback when
   *  the provider does not stream). */
  kind: "token" | "message" | "activity" | "done";
  text?: string | null;
}

/**
 * One row of GET /api/instances/{id}/messages — the persisted transcript
 * (ChatGPT-style history). role=user|agent — a message (agent text is
 * markdown); role=event — a turn card: status started|finished|failed,
 * action/commitSha of the Событие (absent for a failed chat turn — then
 * `text` is the reason), findingsCount.
 */
export interface ChatMessage {
  id: number;
  role: "user" | "agent" | "event";
  text?: string;
  eventId?: number;
  action?: string;
  commitSha?: string;
  status?: "started" | "finished" | "failed";
  findingsCount?: number;
  ts: string;
  traceId?: string;
}
/** Page of the transcript, oldest first; more=true → repeat with before=<first id>. */
export interface ChatHistory {
  messages: ChatMessage[];
  more: boolean;
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
 * Work log (what the agent thinks and does): text — a thought/answer,
 * tool_call — a tool call with its arguments, tool_result — tool name + output
 * preview; taskId marks a Сабагент's frame, none — the lead's.
 */
export interface ActivityEvent {
  kind:
    | "run_started"
    | "chat_user"
    | "chat_agent"
    | "node"
    | "task_started"
    | "task_finished"
    | "task_failed"
    | "task_report"
    | "text"
    | "tool_call"
    | "tool_result"
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

/** GET /api/defaults — what the hub fills into empty fields on create (mirror
 *  of .env); forms show these up front. Keys never cross the wire — only a flag. */
export interface HubDefaults {
  llmApiBase: string;
  llmModel: string;
  sandboxDomain: string;
  sandboxImage: string;
  sandboxApiKeySet: boolean;
  limits: Record<string, number>;
}
