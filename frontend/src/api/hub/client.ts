/**
 * The hub API surface the UI depends on. Implemented by http.ts (real Go
 * backend) and mock.ts (executable spec, default until the backend lands).
 */
import type {
  ActivityEvent,
  AgentBuild,
  AgentBuildInput,
  AgentInstance,
  ChatEvent,
  Finding,
  FindingExportFormat,
  FindingFilters,
  Identity,
  LlmConnection,
  Me,
  Provider,
  ProviderRepo,
  RepoEvent,
  Report,
  Repository,
  Runner,
  TerminalEvent,
  TriggerResult,
  SandboxConnection,
  SandboxInstance,
  Subscription,
} from "./contract.ts";

/** Thrown by me() (and any authed call) on 401 — HubGate turns it into sign-in. */
export type ConnectRepositoryInput =
  | { identityId: number; externalId: string; buildId?: number | null }
  | { url: string; buildId?: number | null };

export class UnauthorizedError extends Error {
  constructor(message = "not signed in") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export interface HubApi {
  // auth + identities
  me(): Promise<Me>;
  /** Kicks off the provider OAuth flow (http: full-page redirect). */
  login(provider: Provider): Promise<void>;
  logout(): Promise<void>;
  listIdentities(): Promise<Identity[]>;
  deleteIdentity(id: number): Promise<void>;
  listIdentityRepos(id: number): Promise<ProviderRepo[]>;

  // repositories + Событие journal
  listRepositories(): Promise<Repository[]>;
  /** Either an own repo via identity (hook mode) or a public repo by URL (watch mode). */
  connectRepository(input: ConnectRepositoryInput): Promise<Repository>;
  setRepositoryBuild(id: number, buildId: number): Promise<Repository>;
  disconnectRepository(id: number): Promise<void>;
  listRepositoryEvents(id: number): Promise<RepoEvent[]>;
  /** Manual agent run — same path as a webhook push. Empty input = HEAD of the default branch.
   *  mode "full" = full security audit of the whole repo (Событие full_scan). */
  triggerRepository(
    id: number,
    input?: { ref?: string; commitSha?: string; mode?: "manual" | "full" },
  ): Promise<TriggerResult>;

  // Подписки — which Сборки watch a repo (upsert per build+repo pair)
  listSubscriptions(repositoryId: number): Promise<Subscription[]>;
  createSubscription(
    repositoryId: number,
    input: { buildId: number; actions?: string[]; refMask?: string | null },
  ): Promise<Subscription>;
  deleteSubscription(id: number): Promise<void>;

  // Сборки
  listBuilds(): Promise<AgentBuild[]>;
  createBuild(input: AgentBuildInput): Promise<AgentBuild>;
  updateBuild(id: number, input: AgentBuildInput): Promise<AgentBuild>;
  deleteBuild(id: number): Promise<void>;

  // connections (keys masked)
  listLlmConnections(): Promise<LlmConnection[]>;
  createLlmConnection(input: { name: string; apiBase: string; apiKey: string; model: string }): Promise<LlmConnection>;
  deleteLlmConnection(id: number): Promise<void>;
  listSandboxConnections(): Promise<SandboxConnection[]>;
  createSandboxConnection(input: { name: string; domain: string; apiKey?: string; image?: string }): Promise<SandboxConnection>;
  deleteSandboxConnection(id: number): Promise<void>;

  // Экземпляры Сэндбоксов — создаёт/убивает юзер, раннер только подключается
  listSandboxInstances(): Promise<SandboxInstance[]>;
  /** Hub calls OpenSandbox create (no-TTL) on that connection. */
  createSandboxInstance(input: { sandboxConnectionId: number }): Promise<SandboxInstance>;
  killSandboxInstance(id: number): Promise<void>;
  /** Bind an Экземпляр Агента to a sandbox (agent_instances.sandbox_instance_id). */
  setInstanceSandbox(instanceId: number, sandboxInstanceId: number): Promise<void>;

  // Экземпляры
  listInstances(repositoryId?: number): Promise<AgentInstance[]>;
  getInstance(id: number): Promise<AgentInstance>;
  /** «Остановить ход»: runner cancels the executing ход (Событие stays unprocessed — resumable). */
  stopInstance(id: number): Promise<void>;
  /** Fast raise: "queued" = runner slots busy, it will raise in background. */
  raiseInstance(id: number): Promise<{ status: "running" | "queued" }>;
  /** «Продолжить»: republish unprocessed События; empty list = nothing to resume. */
  resumeInstance(id: number): Promise<{ eventIds: number[] }>;
  listInstanceReports(id: number): Promise<Report[]>;
  /** Находки of one Экземпляр, filtered server-side (findings v2). */
  listInstanceFindings(id: number, filters?: FindingFilters): Promise<Finding[]>;
  /** GET …/findings/export?format=csv|md → file body as text. */
  exportInstanceFindings(id: number, format: FindingExportFormat, filters?: FindingFilters): Promise<string>;
  /** Находки across every Экземпляр of a repository. */
  listRepositoryFindings(repositoryId: number, filters?: FindingFilters): Promise<Finding[]>;
  exportRepositoryFindings(repositoryId: number, format: FindingExportFormat, filters?: FindingFilters): Promise<string>;
  /** Streams the agent's reply; resolves when the stream ends. */
  chat(instanceId: number, message: string, onEvent: (e: ChatEvent) => void): Promise<void>;
  /** Runs one stream-console command in the Экземпляр's sandbox (running only). */
  terminal(instanceId: number, command: string, onEvent: (e: TerminalEvent) => void): Promise<void>;
  /**
   * Streams activity frames of one ход (run graph, ticket 012). eventId null =
   * live/latest turn; resolves when the stream ends (kind=done included).
   */
  activity(
    instanceId: number,
    eventId: number | null,
    onEvent: (e: ActivityEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>;

  // Раннеры (UI/debug view)
  listRunners(): Promise<Runner[]>;
}
