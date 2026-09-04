/**
 * In-memory hub adapter — the executable spec of backend/docs/openapi.yaml.
 * Default until the Go backend lands (switch: VITE_HUB_API=http). Behavior it
 * pins down: masked keys, connect/disconnect lifecycle, single running
 * instance per repo, chat wakes a down instance and streams tokens.
 */
import type {
  ActivityEvent,
  AgentBuild,
  AgentInstance,
  Finding,
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
  SandboxConnection,
  SandboxInstance,
  Subscription,
  ChatMessage,
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
  { id: 1, identityId: 1, mode: "hook", provider: "github", externalId: "gh-101", owner: "vnkjd", name: "git-agent", defaultBranch: "main", buildId: 1, connectedAt: iso(60 * 24 * 4) },
  { id: 2, identityId: 2, mode: "hook", provider: "gitlab", externalId: "gl-201", owner: "vnkjd", name: "infra-playground", defaultBranch: "main", buildId: null, connectedAt: iso(60 * 5) },
  { id: 3, identityId: null, mode: "watch", provider: "github", externalId: "gh-999", owner: "gin-gonic", name: "gin", defaultBranch: "master", buildId: null, connectedAt: iso(60 * 24) },
];

const events: Record<number, RepoEvent[]> = {
  1: [
    { id: 3, provider: "github", action: "push", commitSha: "9f3c1a2b7d4e", ref: "refs/heads/main", receivedAt: iso(12) },
    { id: 2, provider: "github", action: "pull_request.opened", commitSha: "44adbeef0011", ref: "refs/pull/7/head", receivedAt: iso(95) },
    { id: 1, provider: "github", action: "push", commitSha: "c0ffee123456", ref: "refs/heads/main", receivedAt: iso(60 * 20) },
  ],
  2: [{ id: 4, provider: "gitlab", action: "push", commitSha: "abc123def456", ref: "refs/heads/main", receivedAt: iso(60 * 2) }],
};

// Песочницы создаёт юзер (hub зовёт OpenSandbox, no-TTL); раннер только подключается.
const sandboxInstances: SandboxInstance[] = [
  { id: 11, externalId: "sbx-a1b2c3d4", sandboxConnectionId: 1, status: "alive", createdAt: iso(60 * 24), killedAt: null },
];

const withSandbox = (i: AgentInstance): AgentInstance => {
  const si = sandboxInstances.find((s) => s.id === i.sandboxInstanceId);
  return { ...i, sandboxExternalId: si?.externalId ?? null, sandboxStatus: si?.status ?? null };
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
    {
      id: 1,
      instanceId: 1,
      eventId: 1,
      summary: "Initial scan: FastAPI gateway + LangGraph worker. One high-severity finding (SQL string interpolation in run_store).",
      structured: {
        summary: "Initial scan of the FastAPI gateway and the LangGraph worker. One high-severity injection, one hard-coded secret in the compose file.",
        scope: { eventType: "push", range: "0000000..4f3a9c1", filesTouched: ["infra/db/run_store.py", "deploy/docker-compose.yml", "core/lead/graph.py"], linesChanged: 412 },
        method: ["semgrep default rules", "manual review of db/ and deploy/", "grep for secrets"],
        findingsBySeverity: { high: 1, medium: 1 },
        topRisks: ["SQL string interpolation in run_store.py lets a crafted run id read any row.", "The sandbox api key ships inside the compose file."],
        recommendations: ["Bind parameters in run_store.py.", "Move OPEN_SANDBOX_API_KEY to an env file outside the image.", "Add semgrep to CI."],
        limitations: ["No dynamic testing.", "Frontend not in scope of this turn."],
      },
      createdAt: iso(60 * 19),
    },
  ],
  2: [],
};

const findings: Record<number, Finding[]> = {
  1: [
    {
      id: 1,
      instanceId: 1,
      reportId: 1,
      eventId: 1,
      severity: "high",
      title: "SQL injection via f-string in run lookup",
      description: "The run id from the request is interpolated straight into the SQL text.",
      impact: "Any authenticated caller can read or modify arbitrary rows of hub.runs.",
      confidence: "high",
      category: "injection",
      cwe: "CWE-89",
      cve: null,
      file: "infra/db/run_store.py",
      lineStart: 142,
      lineEnd: 148,
      evidence: 'query = f"SELECT * FROM runs WHERE id = {run_id}"',
      remediation: "Use psycopg parameter binding instead of f-string interpolation.",
      references: ["https://cwe.mitre.org/data/definitions/89.html"],
      blameAuthor: "vnkjd",
      blameEmail: "vnkjd47@gmail.com",
      blameCommit: "4f3a9c1e7b2d",
      blameDate: iso(60 * 24 * 3),
      blameCommitMessage: "run store: lookup by id",
      introducedBy: "this_event",
      createdAt: iso(60 * 19),
    },
    {
      id: 2,
      instanceId: 1,
      reportId: 1,
      eventId: 1,
      severity: "medium",
      title: "Sandbox api key committed in docker-compose",
      description: "A working api key is a literal in the compose file that ships with the image.",
      impact: "Anyone with the image can drive the sandbox host.",
      confidence: "medium",
      category: "secrets",
      cwe: "CWE-798",
      cve: null,
      file: "deploy/docker-compose.yml",
      lineStart: 23,
      lineEnd: 23,
      evidence: "OPEN_SANDBOX_API_KEY: dev-local-key",
      remediation: "Move the sandbox key to an env file excluded from the image.",
      references: [],
      blameAuthor: "vnkjd",
      blameCommit: "91c0de4aa01f",
      blameDate: iso(60 * 24 * 40),
      blameCommitMessage: "deploy: compose for local dev",
      introducedBy: "earlier",
      createdAt: iso(60 * 19),
    },
  ],
  2: [],
};

/** Server-side filter of GET …/findings (mirrors the query params). */
function filterFindings(rows: Finding[], f?: FindingFilters): Finding[] {
  return rows.filter(
    (x) =>
      (!f?.severity || x.severity === f.severity) &&
      (!f?.category || x.category === f.category) &&
      (f?.eventId == null || x.eventId === f.eventId) &&
      (!f?.introducedBy || x.introducedBy === f.introducedBy),
  );
}
/** GET …/findings/export — the file body the hub would send. */
function exportFindings(rows: Finding[], format: "csv" | "md"): string {
  const loc = (x: Finding) => (x.file ? `${x.file}${x.lineStart != null ? `:${x.lineStart}` : ""}` : "");
  const cols = ["severity", "title", "category", "location", "introducedBy", "blameAuthor", "blameCommit", "cwe", "cve", "confidence"];
  const cell = (x: Finding, c: string) => (c === "location" ? loc(x) : String((x as unknown as Record<string, unknown>)[c] ?? ""));
  if (format === "csv") {
    const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s);
    return [cols.join(","), ...rows.map((x) => cols.map((c) => esc(cell(x, c))).join(","))].join("\n");
  }
  return [`| ${cols.join(" | ")} |`, `| ${cols.map(() => "---").join(" | ")} |`, ...rows.map((x) => `| ${cols.map((c) => cell(x, c).replaceAll("|", "\\|")).join(" | ")} |`)].join("\n");
}

const runners: Runner[] = [
  { id: 1, name: "runner-local", address: "127.0.0.1:9090", slots: 4, lastHeartbeatAt: iso(0) },
];

let nextId = 100;
// persisted chat transcript per instance (mirror of hub.activity chat_* rows)
const transcript: (ChatMessage & { instanceId: number })[] = [];

/* Живая лента: repo 1 gets a fresh push Событие every ~40s of wall time, and
   its running agent files a report for it shortly after — so the Playground
   timeline visibly moves on mocks. */
let lastLiveAt = Date.now();
function tickLiveFeed(): void {
  const now = Date.now();
  if (now - lastLiveAt < 40_000) return;
  lastLiveAt = now;
  const sha = Math.floor(Math.random() * 0xffffffffffff)
    .toString(16)
    .padStart(12, "0");
  const event: RepoEvent = {
    id: nextId++,
    provider: "github",
    action: "push",
    commitSha: sha,
    ref: "refs/heads/main",
    receivedAt: new Date().toISOString(),
  };
  events[1] = [event, ...(events[1] ?? [])];
  const inst = instances.find((i) => i.repositoryId === 1 && i.status === "running");
  if (inst) {
    setTimeout(() => {
      (reports[inst.id] ??= []).unshift({
        id: nextId++,
        instanceId: inst.id,
        eventId: event.id,
        summary: `Push ${sha.slice(0, 7)}: reviewed, no new findings.`,
        createdAt: new Date().toISOString(),
      });
    }, 15_000);
  }
}

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
    async connectRepository(input) {
      await delay(500);
      authed();
      if ("url" in input) {
        // watch: public repo by URL — no identity, no webhook (hub checks the public API)
        const m = /^https:\/\/(github|gitlab)\.com\/([^/\s]+(?:\/[^/\s]+)*)\/([^/\s]+?)(?:\.git)?\/?$/.exec(input.url.trim());
        if (!m) throw new Error("400 url must be https://github.com/{owner}/{repo} or https://gitlab.com/{group}/{repo}");
        const [, provider, owner, name] = m as unknown as [string, Provider, string, string];
        if (name === "private") throw new Error("422 repository is private or not found");
        const externalId = `${provider}-${owner}/${name}`;
        if (repositories.some((r) => r.provider === provider && r.externalId === externalId))
          throw new Error("409 repository already connected");
        const repo: Repository = {
          id: nextId++, identityId: null, mode: "watch", provider, externalId, owner, name,
          defaultBranch: "main", buildId: input.buildId ?? builds.find((b) => b.isDefault)?.id ?? null,
          connectedAt: new Date().toISOString(),
        };
        repositories.push(repo);
        events[repo.id] = [];
        return repo;
      }
      const { identityId, externalId, buildId } = input;
      const identity = identities.find((i) => i.id === identityId);
      const src = (providerRepos[identityId] ?? []).find((r) => r.externalId === externalId);
      if (!identity || !src) throw new Error("404 unknown identity or repo");
      if (repositories.some((r) => r.provider === identity.provider && r.externalId === externalId))
        throw new Error("409 repository already connected");
      const repo: Repository = {
        id: nextId++,
        identityId,
        mode: "hook",
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
      tickLiveFeed();
      return [...(events[id] ?? [])];
    },

    async triggerRepository(id, input) {
      await delay(300);
      authed();
      const repo = repositories.find((r) => r.id === id);
      if (!repo) throw new Error("404 repository not found");
      const sha =
        input?.commitSha ??
        Math.floor(Math.random() * 0xffffffffffff)
          .toString(16)
          .padStart(12, "0");
      const event: RepoEvent = {
        id: nextId++,
        provider: repo.provider,
        action: input?.mode === "full" ? "full_scan" : "manual_trigger",
        commitSha: sha,
        ref: `refs/heads/${input?.ref ?? repo.defaultBranch ?? "main"}`,
        receivedAt: new Date().toISOString(),
      };
      events[id] = [event, ...(events[id] ?? [])];
      // Same fan-out as a webhook push: wake the repo's Экземпляры, then a
      // report (and sometimes a finding) lands a little later — the Playground
      // poll picks the progress up.
      const raised = instances.filter((i) => i.repositoryId === id);
      for (const inst of raised) {
        inst.status = "running";
        inst.runnerId = 1;
        inst.updatedAt = new Date().toISOString();
        setTimeout(() => {
          if (Math.random() < 0.4) {
            (findings[inst.id] ??= []).push({
              id: nextId++,
              instanceId: inst.id,
              reportId: null,
              severity: "low",
              cwe: "CWE-117",
              cve: null,
              file: "pkg/logger.py",
              lineStart: 12,
              lineEnd: 12,
              evidence: "logger.info(f\"user input: {raw}\")",
              remediation: "Sanitize newlines before logging user-controlled input.",
              createdAt: new Date().toISOString(),
            });
          }
          (reports[inst.id] ??= []).unshift({
            id: nextId++,
            instanceId: inst.id,
            eventId: event.id,
            summary: `Manual run @ ${sha.slice(0, 7)}: reviewed the tree, see findings if any.`,
            createdAt: new Date().toISOString(),
          });
        }, 12_000);
      }
      return { commitSha: sha, duplicate: false, instanceIds: raised.map((i) => i.id) };
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
    async getDefaults() {
      await delay();
      return { llmApiBase: "http://localhost:8080/v1", llmModel: "qwen3-coder", sandboxDomain: "localhost:8090", sandboxImage: "git-agent/sandbox:strix", sandboxApiKeySet: true, limits: { maxSubagents: 3, maxTotalSubagents: 6, subagentTimeout: 600, queueTimeout: 300 } };
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

    async listSandboxInstances() {
      await delay();
      authed();
      return sandboxInstances.map((s) => ({ ...s }));
    },
    async createSandboxInstance({ sandboxConnectionId }) {
      await delay(600);
      authed();
      if (!sandboxConnections.some((c) => c.id === sandboxConnectionId))
        throw new Error("404 sandbox connection not found");
      const si: SandboxInstance = {
        id: nextId++,
        externalId: `sbx-${Math.floor(Math.random() * 0xffffff).toString(16).padStart(6, "0")}`,
        sandboxConnectionId,
        status: "alive",
        createdAt: new Date().toISOString(),
        killedAt: null,
      };
      sandboxInstances.push(si);
      return { ...si };
    },
    async killSandboxInstance(id) {
      await delay(400);
      const si = sandboxInstances.find((s) => s.id === id);
      if (!si) throw new Error("404 sandbox instance not found");
      si.status = "dead";
      si.killedAt = new Date().toISOString();
    },
    async setInstanceSandbox(instanceId, sandboxInstanceId) {
      await delay();
      const inst = instances.find((i) => i.id === instanceId);
      if (!inst) throw new Error("404 instance not found");
      if (!sandboxInstances.some((s) => s.id === sandboxInstanceId))
        throw new Error("409 unknown sandbox instance");
      inst.sandboxInstanceId = sandboxInstanceId;
      inst.updatedAt = new Date().toISOString();
    },

    async listInstances(repositoryId) {
      await delay();
      authed();
      return instances
        .filter((i) => repositoryId == null || i.repositoryId === repositoryId)
        .map(withSandbox);
    },
    async getInstance(id) {
      await delay();
      const inst = instances.find((i) => i.id === id);
      if (!inst) throw new Error("404 instance not found");
      return withSandbox(inst);
    },
    async stopInstance(id) {
      await delay(400);
      const inst = instances.find((i) => i.id === id);
      if (!inst) throw new Error("404 instance not found");
      inst.status = "down";
      inst.runnerId = null;
      inst.updatedAt = new Date().toISOString();
    },
    async raiseInstance(id) {
      await delay(300);
      const inst = instances.find((i) => i.id === id);
      if (!inst) throw new Error("404 instance not found");
      inst.status = "running";
      inst.runnerId = 1;
      inst.updatedAt = new Date().toISOString();
      return { status: "running" as const };
    },
    async resumeInstance(id) {
      await delay(300);
      const inst = instances.find((i) => i.id === id);
      if (!inst) throw new Error("404 instance not found");
      // незавершённое Событие = Событие репозитория без Отчёта этого Экземпляра
      const unfinished = (events[inst.repositoryId] ?? []).filter(
        (e) => !(reports[inst.id] ?? []).some((r) => r.eventId === e.id),
      );
      if (unfinished.length > 0) {
        // раннер получает Событие из очереди, поднимает Экземпляр и доисполняет ход
        inst.status = "running";
        inst.runnerId = 1;
        inst.updatedAt = new Date().toISOString();
        const eventId = unfinished[0].id;
        setTimeout(() => {
          (reports[inst.id] ??= []).unshift({
            id: nextId++,
            instanceId: inst.id,
            eventId,
            summary: "Resumed from checkpoint: finished the interrupted ход.",
            createdAt: new Date().toISOString(),
          });
        }, 8_000);
      }
      return { eventIds: unfinished.map((e) => e.id) };
    },
    async listInstanceReports(id) {
      await delay();
      return [...(reports[id] ?? [])];
    },
    async listInstanceFindings(id, f) {
      await delay();
      return filterFindings(findings[id] ?? [], f);
    },
    async exportInstanceFindings(id, format, f) {
      await delay();
      return exportFindings(filterFindings(findings[id] ?? [], f), format);
    },
    async raiseRepository(id) {
      await delay(300);
      authed();
      const mine = instances.filter((i) => i.repositoryId === id);
      for (const inst of mine) {
        inst.status = "running";
        inst.runnerId = 1;
        inst.updatedAt = new Date().toISOString();
      }
      return { instances: mine.map((i) => ({ id: i.id, status: "running" as const })) };
    },
    async listRepositoryReports(id) {
      await delay();
      const ids = instances.filter((i) => i.repositoryId === id).map((i) => i.id);
      return ids.flatMap((iid) => reports[iid] ?? []).sort((a, b) => b.id - a.id);
    },
    async listRepositoryFindings(repositoryId, f) {
      await delay();
      const ids = instances.filter((i) => i.repositoryId === repositoryId).map((i) => i.id);
      return filterFindings(ids.flatMap((id) => findings[id] ?? []), f);
    },
    async exportRepositoryFindings(repositoryId, format, f) {
      await delay();
      const ids = instances.filter((i) => i.repositoryId === repositoryId).map((i) => i.id);
      return exportFindings(filterFindings(ids.flatMap((id) => findings[id] ?? []), f), format);
    },

    async listRunners() {
      await delay();
      authed();
      return runners.map((r) => ({ ...r, lastHeartbeatAt: new Date().toISOString() }));
    },

    async listMessages(instanceId, opts) {
      await delay();
      authed();
      const all = transcript.filter((m) => m.instanceId === instanceId && (!opts?.before || m.id < opts.before));
      const limit = opts?.limit ?? 50;
      const page = all.slice(-limit);
      return { messages: page.map(({ instanceId: _i, ...m }) => m), more: all.length > page.length };
    },
    async chat(instanceId, message, onEvent) {
      authed();
      const inst = instances.find((i) => i.id === instanceId);
      if (!inst) throw new Error("404 instance not found");
      transcript.push({ instanceId, id: nextId++, role: "user", text: message, ts: new Date().toISOString() });
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
      onEvent({ kind: "message", text: reply });
      transcript.push({ instanceId, id: nextId++, role: "agent", text: reply, ts: new Date().toISOString() });
      onEvent({ kind: "done" });
    },

    async activity(instanceId, eventId, onEvent, signal) {
      authed();
      if (!instances.find((i) => i.id === instanceId)) throw new Error("404 instance not found");
      const ts = () => new Date().toISOString();
      const frames: ActivityEvent[] = [
        { kind: "run_started", ts: ts() },
        { kind: "node", description: "lead", status: "done", findingsCount: 0, ts: ts() },
        { kind: "task_started", taskId: "t1", description: "review auth flow", status: "queued", ts: ts() },
        { kind: "task_started", taskId: "t1", status: "working", ts: ts() },
        { kind: "task_started", taskId: "t2", description: "scan deps for CVEs", status: "working", ts: ts() },
        { kind: "task_finished", taskId: "t1", status: "done", findingsCount: 1, ts: ts() },
        { kind: "task_report", taskId: "t1", description: "Проверил auth-флоу: одна слабая проверка сессии (см. Находку). Остальное чисто.", ts: ts() },
        { kind: "task_failed", taskId: "t2", status: "timeout", description: "600s", ts: ts() },
        { kind: "node", description: "lead", status: "done", findingsCount: 2, ts: ts() },
        { kind: "run_finished", findingsCount: 2, ts: ts() },
        { kind: "done" },
      ];
      // прошлый ход — мгновенный реплей; live — кадры «идут» с паузами
      for (const f of frames) {
        if (signal?.aborted) return;
        if (eventId == null) await delay(600);
        onEvent(f);
      }
    },

    async terminal(instanceId, command, onEvent) {
      authed();
      const inst = instances.find((i) => i.id === instanceId);
      if (!inst) throw new Error("404 instance not found");
      if (inst.status !== "running") throw new Error("409 instance is down — raise the agent first");
      await delay(300);
      const cd = command.match(/^cd\s+(\S+)/);
      if (!cd) onEvent({ kind: "output", text: `mock sandbox: ran \`${command}\`` });
      onEvent({ kind: "exit", code: 0, cwd: cd ? `/repo/${cd[1]}` : "/repo" });
      onEvent({ kind: "done" });
    },
  };
}
