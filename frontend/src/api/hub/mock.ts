/**
 * In-memory hub adapter — the executable spec of backend/docs/openapi.yaml.
 * Default until the Go backend lands (switch: VITE_HUB_API=http). Behavior it
 * pins down: masked keys, connect/disconnect lifecycle, single running
 * instance per repo, chat wakes a down instance and streams tokens.
 */
import type {
  AgentBuild,
  AgentInstance,
  Finding,
  Identity,
  LlmConnection,
  Me,
  ProviderRepo,
  RepoEvent,
  Report,
  Repository,
  SandboxConnection,
  Subscription,
} from "./contract.ts";
import { UnauthorizedError, type HubApi } from "./client.ts";

const delay = (ms = 180) => new Promise<void>((r) => setTimeout(r, ms));
const mask = (key: string) => (key ? `${key.slice(0, 3)}…${key.slice(-2)}` : "—");
const iso = (minsAgo: number) => new Date(Date.now() - minsAgo * 60_000).toISOString();

const identities: Identity[] = [
  { id: 1, provider: "github", username: "vnkjd", createdAt: iso(60 * 24 * 30) },
  { id: 2, provider: "gitlab", username: "vnkjd", createdAt: iso(60 * 24 * 7) },
];

const providerRepos: Record<number, ProviderRepo[]> = {
  1: [
    { externalId: "gh-101", owner: "vnkjd", name: "git-agent", defaultBranch: "main", private: false },
    { externalId: "gh-102", owner: "vnkjd", name: "dotfiles", defaultBranch: "master", private: false },
    { externalId: "gh-103", owner: "vnkjd", name: "secret-sauce", defaultBranch: "main", private: true },
  ],
  2: [{ externalId: "gl-201", owner: "vnkjd", name: "infra-playground", defaultBranch: "main", private: true }],
};

let me: Me | null = { id: 1, displayName: "vnkjd", identities };

const llmConnections: LlmConnection[] = [
  { id: 1, name: "openrouter", apiBase: "https://openrouter.ai/api/v1", apiKeyMasked: "sk-…4f", model: "anthropic/claude-sonnet-4" },
];
const sandboxConnections: SandboxConnection[] = [
  { id: 1, name: "local-opensandbox", domain: "http://localhost:8090", apiKeyMasked: "dev…ey", image: "opensandbox/base" },
];

const builds: AgentBuild[] = [
  {
    id: 1,
    name: "default-reviewer",
    llmConnectionId: 1,
    sandboxConnectionId: 1,
    prompt: "Review every push for security issues.",
    memoryPreset: "prod_v2",
    limits: { maxSubagents: 3, tokenBudget: 500_000 },
    isDefault: true,
    createdAt: iso(60 * 24 * 5),
  },
  { id: 2, name: "docs-watcher", llmConnectionId: 1, sandboxConnectionId: 1, memoryPreset: "prod", isDefault: false, createdAt: iso(60 * 24) },
];

const repositories: Repository[] = [
  { id: 1, identityId: 1, provider: "github", externalId: "gh-101", owner: "vnkjd", name: "git-agent", defaultBranch: "main", buildId: 1, connectedAt: iso(60 * 24 * 4) },
  { id: 2, identityId: 2, provider: "gitlab", externalId: "gl-201", owner: "vnkjd", name: "infra-playground", defaultBranch: "main", buildId: null, connectedAt: iso(60 * 5) },
];

const events: Record<number, RepoEvent[]> = {
  1: [
    { id: 3, provider: "github", action: "push", commitSha: "9f3c1a2b7d4e", ref: "refs/heads/main", receivedAt: iso(12) },
    { id: 2, provider: "github", action: "pull_request.opened", commitSha: "44adbeef0011", ref: "refs/pull/7/head", receivedAt: iso(95) },
    { id: 1, provider: "github", action: "push", commitSha: "c0ffee123456", ref: "refs/heads/main", receivedAt: iso(60 * 20) },
  ],
  2: [{ id: 4, provider: "gitlab", action: "push", commitSha: "abc123def456", ref: "refs/heads/main", receivedAt: iso(60 * 2) }],
};

const instances: AgentInstance[] = [
  { id: 1, buildId: 1, repositoryId: 1, sandboxInstanceId: 11, threadId: "inst-1", status: "running", runnerId: 1, updatedAt: iso(3) },
  { id: 2, buildId: 1, repositoryId: 2, sandboxInstanceId: null, threadId: "inst-2", status: "down", runnerId: null, updatedAt: iso(60 * 2) },
  // веер: второй watcher того же репо (docs-watcher подписан на push @ release/*)
  { id: 3, buildId: 2, repositoryId: 1, sandboxInstanceId: null, threadId: "inst-3", status: "down", runnerId: null, updatedAt: iso(60 * 8) },
];

// Подписки (ticket 011): upsert по (buildId, repositoryId); [] actions = все,
// null refMask = любой ref. Репо 2 без подписок → его обслуживает default.
const subscriptions: Subscription[] = [
  { id: 1, buildId: 1, repositoryId: 1, actions: [], refMask: null, createdAt: iso(60 * 24 * 4) },
  { id: 2, buildId: 2, repositoryId: 1, actions: ["push"], refMask: "release/*", createdAt: iso(60 * 24) },
];

const reports: Record<number, Report[]> = {
  1: [
    { id: 2, instanceId: 1, eventId: 3, summary: "Push 9f3c1a2: no new findings. The auth refactor removes the token-in-query pattern flagged earlier.", createdAt: iso(10) },
    { id: 1, instanceId: 1, eventId: 1, summary: "Initial scan: FastAPI gateway + LangGraph worker. One high-severity finding (SQL string interpolation in run_store).", createdAt: iso(60 * 19) },
  ],
  2: [],
};

const findings: Record<number, Finding[]> = {
  1: [
    {
      id: 1,
      instanceId: 1,
      reportId: 1,
      severity: "high",
      cwe: "CWE-89",
      cve: null,
      file: "infra/db/run_store.py",
      lineStart: 142,
      lineEnd: 148,
      evidence: 'query = f"SELECT * FROM runs WHERE id = {run_id}"',
      remediation: "Use psycopg parameter binding instead of f-string interpolation.",
      createdAt: iso(60 * 19),
    },
    {
      id: 2,
      instanceId: 1,
      reportId: 1,
      severity: "med",
      cwe: "CWE-798",
      cve: null,
      file: "deploy/docker-compose.yml",
      lineStart: 23,
      lineEnd: 23,
      evidence: "OPEN_SANDBOX_API_KEY: dev-local-key",
      remediation: "Move the sandbox key to an env file excluded from the image.",
      createdAt: iso(60 * 19),
    },
  ],
  2: [],
};

let nextId = 100;

function authed(): void {
  if (!me) throw new UnauthorizedError();
}

export function createMockHubApi(): HubApi {
  return {
    async me() {
      await delay();
      authed();
      return { ...me!, identities: [...identities] };
    },
    async login() {
      await delay();
      me = { id: 1, displayName: "vnkjd", identities };
    },
    async logout() {
      await delay();
      me = null;
    },
    async listIdentities() {
      await delay();
      authed();
      return [...identities];
    },
    async deleteIdentity(id) {
      await delay();
      const i = identities.findIndex((x) => x.id === id);
      if (i >= 0) identities.splice(i, 1);
    },
    async listIdentityRepos(id) {
      await delay(400);
      authed();
      return providerRepos[id] ?? [];
    },

    async listRepositories() {
      await delay();
      authed();
      return [...repositories];
    },
    async connectRepository({ identityId, externalId, buildId }) {
      await delay(500);
      authed();
      const identity = identities.find((i) => i.id === identityId);
      const src = (providerRepos[identityId] ?? []).find((r) => r.externalId === externalId);
      if (!identity || !src) throw new Error("404 unknown identity or repo");
      if (repositories.some((r) => r.provider === identity.provider && r.externalId === externalId))
        throw new Error("409 repository already connected");
      const repo: Repository = {
        id: nextId++,
        identityId,
        provider: identity.provider,
        externalId,
        owner: src.owner,
        name: src.name,
        defaultBranch: src.defaultBranch,
        buildId: buildId ?? builds.find((b) => b.isDefault)?.id ?? null,
        connectedAt: new Date().toISOString(),
      };
      repositories.push(repo);
      events[repo.id] = [];
      return repo;
    },
    async setRepositoryBuild(id, buildId) {
      await delay();
      const repo = repositories.find((r) => r.id === id);
      if (!repo) throw new Error("404 repository not found");
      repo.buildId = buildId;
      return { ...repo };
    },
    async disconnectRepository(id) {
      await delay();
      const i = repositories.findIndex((r) => r.id === id);
      if (i >= 0) repositories.splice(i, 1);
      for (let j = subscriptions.length - 1; j >= 0; j--)
        if (subscriptions[j].repositoryId === id) subscriptions.splice(j, 1);
    },
    async listRepositoryEvents(id) {
      await delay();
      return [...(events[id] ?? [])];
    },

    async listSubscriptions(repositoryId) {
      await delay();
      authed();
      return subscriptions.filter((s) => s.repositoryId === repositoryId);
    },
    async createSubscription(repositoryId, { buildId, actions, refMask }) {
      await delay();
      authed();
      if (!builds.some((b) => b.id === buildId)) throw new Error("404 build not found");
      const existing = subscriptions.find((s) => s.repositoryId === repositoryId && s.buildId === buildId);
      if (existing) {
        existing.actions = actions ?? [];
        existing.refMask = refMask ?? null;
        return { ...existing };
      }
      const sub: Subscription = {
        id: nextId++,
        buildId,
        repositoryId,
        actions: actions ?? [],
        refMask: refMask ?? null,
        createdAt: new Date().toISOString(),
      };
      subscriptions.push(sub);
      return sub;
    },
    async deleteSubscription(id) {
      await delay();
      const i = subscriptions.findIndex((s) => s.id === id);
      if (i >= 0) subscriptions.splice(i, 1);
    },

    async listBuilds() {
      await delay();
      authed();
      return [...builds];
    },
    async createBuild(input) {
      await delay();
      const build: AgentBuild = { ...input, id: nextId++, createdAt: new Date().toISOString() };
      if (build.isDefault) builds.forEach((b) => (b.isDefault = false));
      builds.push(build);
      return build;
    },
    async updateBuild(id, input) {
      await delay();
      const build = builds.find((b) => b.id === id);
      if (!build) throw new Error("404 build not found");
      Object.assign(build, input);
      if (build.isDefault) builds.forEach((b) => b.id !== id && (b.isDefault = false));
      return { ...build };
    },
    async deleteBuild(id) {
      await delay();
      const i = builds.findIndex((b) => b.id === id);
      if (i >= 0) builds.splice(i, 1);
    },

    async listLlmConnections() {
      await delay();
      authed();
      return [...llmConnections];
    },
    async createLlmConnection({ name, apiBase, apiKey, model }) {
      await delay();
      const c: LlmConnection = { id: nextId++, name, apiBase, apiKeyMasked: mask(apiKey), model };
      llmConnections.push(c);
      return c;
    },
    async deleteLlmConnection(id) {
      await delay();
      const i = llmConnections.findIndex((c) => c.id === id);
      if (i >= 0) llmConnections.splice(i, 1);
    },
    async listSandboxConnections() {
      await delay();
      authed();
      return [...sandboxConnections];
    },
    async createSandboxConnection({ name, domain, apiKey, image }) {
      await delay();
      const c: SandboxConnection = { id: nextId++, name, domain, apiKeyMasked: apiKey ? mask(apiKey) : null, image: image ?? null };
      sandboxConnections.push(c);
      return c;
    },
    async deleteSandboxConnection(id) {
      await delay();
      const i = sandboxConnections.findIndex((c) => c.id === id);
      if (i >= 0) sandboxConnections.splice(i, 1);
    },

    async listInstances(repositoryId) {
      await delay();
      authed();
      return instances.filter((i) => repositoryId == null || i.repositoryId === repositoryId);
    },
    async getInstance(id) {
      await delay();
      const inst = instances.find((i) => i.id === id);
      if (!inst) throw new Error("404 instance not found");
      return { ...inst };
    },
    async stopInstance(id) {
      await delay(400);
      const inst = instances.find((i) => i.id === id);
      if (!inst) throw new Error("404 instance not found");
      inst.status = "down";
      inst.runnerId = null;
      inst.updatedAt = new Date().toISOString();
    },
    async listInstanceReports(id) {
      await delay();
      return [...(reports[id] ?? [])];
    },
    async listInstanceFindings(id) {
      await delay();
      return [...(findings[id] ?? [])];
    },

    async chat(instanceId, message, onEvent) {
      authed();
      const inst = instances.find((i) => i.id === instanceId);
      if (!inst) throw new Error("404 instance not found");
      if (inst.status === "down") {
        onEvent({ kind: "activity", text: "waking instance on runner…" });
        await delay(700);
        inst.status = "running";
        inst.runnerId = 1;
        inst.updatedAt = new Date().toISOString();
      }
      onEvent({ kind: "activity", text: "reading checkpoint thread…" });
      await delay(500);
      const reply =
        `About "${message.slice(0, 60)}": from what I've accumulated on ` +
        `${repositories.find((r) => r.id === inst.repositoryId)?.name ?? "this repo"} so far, ` +
        `the last push touched the auth flow; no new findings beyond what's in the reports. ` +
        `Ask me to re-check a specific file if you want a deeper look.`;
      for (const word of reply.split(/(?<= )/)) {
        onEvent({ kind: "token", text: word });
        await delay(30);
      }
      onEvent({ kind: "done" });
    },
  };
}
