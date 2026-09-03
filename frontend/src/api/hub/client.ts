/**
 * The hub API surface the UI depends on. Implemented by http.ts (real Go
 * backend) and mock.ts (executable spec, default until the backend lands).
 */
import type {
  AgentBuild,
  AgentBuildInput,
  AgentInstance,
  ChatEvent,
  Finding,
  Identity,
  LlmConnection,
  Me,
  Provider,
  ProviderRepo,
  RepoEvent,
  Report,
  Repository,
  Runner,
  SandboxConnection,
  Subscription,
} from "./contract.ts";

/** Thrown by me() (and any authed call) on 401 — HubGate turns it into sign-in. */
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
  connectRepository(input: { identityId: number; externalId: string; buildId?: number | null }): Promise<Repository>;
  setRepositoryBuild(id: number, buildId: number): Promise<Repository>;
  disconnectRepository(id: number): Promise<void>;
  listRepositoryEvents(id: number): Promise<RepoEvent[]>;

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

  // Экземпляры
  listInstances(repositoryId?: number): Promise<AgentInstance[]>;
  getInstance(id: number): Promise<AgentInstance>;
  stopInstance(id: number): Promise<void>;
  listInstanceReports(id: number): Promise<Report[]>;
  listInstanceFindings(id: number): Promise<Finding[]>;
  /** Streams the agent's reply; resolves when the stream ends. */
  chat(instanceId: number, message: string, onEvent: (e: ChatEvent) => void): Promise<void>;

  // Раннеры (UI/debug view)
  listRunners(): Promise<Runner[]>;
}
