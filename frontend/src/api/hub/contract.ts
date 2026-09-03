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

/** Экземпляр Агента — the long-lived per-repository agent. */
export interface AgentInstance {
  id: number;
  buildId: number;
  repositoryId: number;
  sandboxInstanceId?: number | null;
  threadId?: string;
  status: InstanceStatus;
  runnerId?: number | null;
  updatedAt?: string;
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
