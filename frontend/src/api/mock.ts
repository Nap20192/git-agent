/**
 * In-memory mock adapter — the executable spec for the contract. Seeds a live
 * 3-node pipeline run that advances through scan → parse → report, plus a static
 * completed multi-sub-agent run, historical runs, connections, sandboxes, and the
 * skills/capabilities catalog. Everything speaks the real backend's dialect.
 */
import type {
  Capability,
  Connection,
  GraphNode,
  MemoryPreset,
  NodeSpec,
  NodeStatus,
  Report,
  Run,
  RunEvent,
  RunGraph,
  RunStatus,
  SandboxSpec,
  SubmitRunRequest,
  SubmitRunResponse,
} from "./contract.ts";
import { isResumable, isTerminal } from "./contract.ts";
import type { GitAgentApi, StreamOptions, Unsubscribe } from "./client.ts";
import {
  AGENT_RUN_ID,
  CAPABILITIES,
  CONNECTIONS,
  LIVE_REPO,
  LIVE_RUN_ID,
  MEMORY_PRESETS,
  REPORTS,
  SANDBOXES,
  agentRunEvents,
  graphFor,
  historicalRuns,
  nodeSpec,
} from "./demo-data.ts";

const TICK_MS = 1800;
const PIPELINE = ["scan", "parse", "report"] as const;

function normalizeRepo(url: string): string {
  const u = (url || "")
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/^github\.com\//, "")
    .replace(/\.git$/, "")
    .replace(/\/$/, "");
  return u || LIVE_REPO;
}

/** Node status for the live pipeline at a given phase (0=scan..2=report, 3=done). */
function pipelineNodeStatus(nodeId: string, phase: number, status: RunStatus): NodeStatus {
  const idx = PIPELINE.indexOf(nodeId as (typeof PIPELINE)[number]);
  if (status === "succeeded" || phase > 2) return "completed";
  if (phase > idx) return "completed";
  if (phase === idx) {
    if (status === "interrupted" || status === "failed") return "error";
    return "running";
  }
  return "pending";
}

/** Node status for a finished historical run. */
function historicalNodeStatus(nodeId: string, status: RunStatus): NodeStatus {
  if (status === "succeeded") return "completed";
  if (status === "pending") return "pending";
  const idx = PIPELINE.indexOf(nodeId as (typeof PIPELINE)[number]);
  if (status === "failed") return idx < 1 ? "completed" : idx === 1 ? "error" : "pending";
  // interrupted: scan done, parse halted, report pending
  return idx < 1 ? "completed" : idx === 1 ? "error" : "pending";
}

class LivePipelineRun {
  events: RunEvent[] = [];
  private subs = new Set<(e: RunEvent) => void>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private cursor = 0;
  phase = 0;

  constructor(public run: Run, repo: string) {
    this.emit("log", "orchestrator", `submit accepted · target github.com/${repo} @ main`);
    this.emit("node_update", "scan", "scan started · git clone --depth 1");
    this.recompute();
    this.timer = setInterval(() => this.tick(), TICK_MS);
  }

  private tick() {
    const s = this.run;
    if (s.status !== "running") return;
    s.metrics.elapsedSec += 2;
    if (this.phase >= PIPELINE.length) {
      s.status = "succeeded";
      s.finishedAt = new Date().toISOString();
      s.hasReport = true;
      this.recompute();
      this.emit("status", "report", "succeeded", { kind: "status", status: "succeeded" });
      this.stopClock();
      return;
    }
    const finished = PIPELINE[this.phase];
    this.emit("node_update", finished, `${finished} finished`);
    this.phase += 1;
    if (this.phase < PIPELINE.length) {
      const next = PIPELINE[this.phase];
      this.emit("node_update", next, `${next} started`);
    }
    this.recompute();
  }

  private recompute() {
    const active = PIPELINE.filter((n) => pipelineNodeStatus(n, this.phase, this.run.status) === "running").length;
    this.run.metrics.agentsActive = active;
    this.run.metrics.agentsTotal = PIPELINE.length;
  }

  private emit(type: RunEvent["type"], agent: string, message: string, data?: RunEvent["data"]) {
    const e: RunEvent = { cursor: ++this.cursor, ts: new Date().toISOString(), type, agent, level: "info", message, data };
    this.events.push(e);
    for (const fn of this.subs) fn(e);
  }

  cancel() {
    if (isTerminal(this.run.status)) return;
    this.run.status = "interrupted";
    this.run.stopReason = "cancelled";
    this.run.finishedAt = new Date().toISOString();
    this.recompute();
    this.emit("status", PIPELINE[Math.min(this.phase, 2)], "interrupted · cancelled", { kind: "status", status: "interrupted" });
    this.stopClock();
  }

  nodeStatus(nodeId: string): NodeStatus {
    return pipelineNodeStatus(nodeId, this.phase, this.run.status);
  }

  subscribe(fromCursor: number, fn: (e: RunEvent) => void): Unsubscribe {
    for (const e of this.events) if (e.cursor > fromCursor) fn(e);
    this.subs.add(fn);
    return () => this.subs.delete(fn);
  }

  private stopClock() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
  dispose() {
    this.stopClock();
    this.subs.clear();
  }
}

function makeLiveRun(id: string, repo: string): Run {
  const now = new Date().toISOString();
  const conn = CONNECTIONS[0];
  return {
    id, repositoryId: "repo-live", repoUrl: `github.com/${repo}`, repo, commitSha: "a1b2c3d",
    status: "running", error: null, stopReason: null, cancelRequestedAt: null, attempt: 1,
    connection: { apiBase: conn.apiBase, model: conn.model, keyMasked: conn.keyMasked },
    sandbox: "python", memoryPreset: "prod_v2", hasReport: false,
    createdAt: now, startedAt: now, finishedAt: null, updatedAt: now,
    metrics: { agentsActive: 1, agentsTotal: 3, elapsedSec: 0, tokenUsage: null },
  };
}

function liveReport(run: Run): Report {
  return {
    repoUrl: run.repoUrl, commit: run.commitSha ?? "HEAD",
    description: "A payments API service. The scan mapped its routes and modules; parse extracted handlers and read the dependency manifest; the report node assembled the structured summary.",
    structure: { fileCount: 88, totalBytes: 240_000, truncated: false, languages: { ".ts": 61, ".json": 8, ".md": 4, "(none)": 15 }, keyFiles: ["package.json", "README.md", "Dockerfile"], files: ["src/api/orders.ts", "src/auth/jwt.ts", "src/repo/search.ts"] },
    modules: [{ path: "src/api/orders.ts", docstring: null, classes: ["OrderController"], functions: ["getOrder", "listOrders"] }],
    dependencies: ["express", "pg", "jsonwebtoken", "zod"],
    skippedFiles: [],
  };
}

export function createMockApi(): GitAgentApi {
  const history = historicalRuns();
  let live = new LivePipelineRun(makeLiveRun(LIVE_RUN_ID, LIVE_REPO), LIVE_REPO);
  const connections = [...CONNECTIONS];
  const sandboxes = [...SANDBOXES];

  const findRun = (id: string): Run | undefined =>
    id === live.run.id ? live.run : history.find((r) => r.id === id);

  return {
    listRuns: () => Promise.resolve([live.run, ...history]),
    getRun: (id) => {
      const r = findRun(id);
      return r ? Promise.resolve(r) : Promise.reject(new Error(`404 run ${id} not found`));
    },
    submitRun: (req: SubmitRunRequest): Promise<SubmitRunResponse> => {
      const repo = normalizeRepo(req.repoUrl);
      // idempotency demo: same repo as the in-flight live run → attach
      if (!isTerminal(live.run.status) && live.run.repo === repo) {
        return Promise.resolve({ run: live.run, disposition: "attached" });
      }
      live.dispose();
      live = new LivePipelineRun(makeLiveRun(`run-${1043 + history.length}`, repo), repo);
      return Promise.resolve({ run: live.run, disposition: "created" });
    },
    cancelRun: (id) => {
      if (id === live.run.id) live.cancel();
      const r = findRun(id);
      return r ? Promise.resolve(r) : Promise.reject(new Error("404"));
    },
    resumeRun: (id): Promise<SubmitRunResponse> => {
      const r = findRun(id);
      if (!r) return Promise.reject(new Error("404"));
      if (!isResumable(r.status)) return Promise.resolve({ run: r, disposition: "already_succeeded" });
      if (id === live.run.id) {
        live.dispose();
        live = new LivePipelineRun(makeLiveRun(LIVE_RUN_ID, live.run.repo), live.run.repo);
        live.run.attempt = r.attempt + 1;
        return Promise.resolve({ run: live.run, disposition: "resumed" });
      }
      r.status = "running";
      r.attempt += 1;
      r.error = null;
      r.finishedAt = null;
      return Promise.resolve({ run: r, disposition: "resumed" });
    },
    getReport: (runId) => {
      if (REPORTS[runId]) return Promise.resolve(REPORTS[runId]);
      if (runId === live.run.id && live.run.status === "succeeded") return Promise.resolve(liveReport(live.run));
      return Promise.reject(new Error("404 no report"));
    },
    getGraph: (runId): Promise<RunGraph> => {
      const { nodes, edges } = graphFor(runId);
      const withStatus: GraphNode[] = nodes.map((n) => {
        if (runId === live.run.id) return { ...n, status: live.nodeStatus(n.id) };
        if (runId === AGENT_RUN_ID) return n; // static: already completed
        const r = findRun(runId);
        return { ...n, status: r ? historicalNodeStatus(n.id, r.status) : "pending" };
      });
      return Promise.resolve({ runId, nodes: withStatus, edges });
    },
    getNodeSpec: (runId, nodeId): Promise<NodeSpec> => {
      const spec = nodeSpec(runId, nodeId);
      return spec ? Promise.resolve(spec) : Promise.reject(new Error("404 no spec"));
    },
    streamRunEvents: (runId, opts: StreamOptions): Unsubscribe => {
      if (runId === live.run.id) return live.subscribe(opts.cursor ?? 0, opts.onEvent);
      if (runId === AGENT_RUN_ID) {
        for (const e of agentRunEvents()) if (e.cursor > (opts.cursor ?? 0)) opts.onEvent(e);
        return () => {};
      }
      return () => {};
    },

    listConnections: () => Promise.resolve(connections),
    createConnection: (input) => {
      const c: Connection = {
        id: `conn-${connections.length + 1}`, name: input.name, apiBase: input.apiBase, model: input.model,
        keyMasked: input.apiKey ? `${input.apiKey.slice(0, 6)}••••••` : "— none —",
        createdAt: new Date().toISOString(), lastCheck: null,
      };
      connections.push(c);
      return Promise.resolve(c);
    },
    deleteConnection: (id) => {
      const i = connections.findIndex((c) => c.id === id);
      if (i >= 0) connections.splice(i, 1);
      return Promise.resolve();
    },
    checkConnection: (id) => {
      const c = connections.find((x) => x.id === id);
      if (!c) return Promise.reject(new Error("404"));
      c.lastCheck = { ok: c.name !== "ollama-local", latencyMs: 290, at: new Date().toISOString() };
      return Promise.resolve(c);
    },

    listSandboxes: () => Promise.resolve(sandboxes),
    createSandbox: (input) => {
      const s: SandboxSpec = {
        id: `sbx-${sandboxes.length + 1}`, name: input.name, kind: input.kind,
        image: input.image ?? null, workdir: input.workdir ?? null,
        createdAt: new Date().toISOString(), runCount: 0,
      };
      sandboxes.push(s);
      return Promise.resolve(s);
    },

    listCapabilities: (): Promise<Capability[]> => Promise.resolve(CAPABILITIES),
    listMemoryPresets: (): Promise<MemoryPreset[]> => Promise.resolve(MEMORY_PRESETS),
  };
}
