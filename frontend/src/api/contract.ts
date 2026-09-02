/**
 * Backend <-> Frontend contract for git-agent.
 *
 * Grounded in the REAL backend at repo HEAD (master 68a7c56), including the new
 * sub-agent system (core/agents/subagents/):
 *   - runs table + core/runtime/schemas.py            -> Run, RunStatus, SubmitDisposition
 *   - core/agents/nodes.py::report                    -> Report
 *   - LangGraph graph + run_events / task_* stream     -> RunGraph, RunEvent
 *   - core/agents/subagents/contract.py + registry.py  -> SubagentStatus, TaskDelegation
 *   - core/agents/subagents/task_tool.py               -> task_* stream events, TokenUsage
 *   - core/agents/tools.py                             -> the sandbox toolset (sandbox_run, read_file)
 *   - sandboxes table                                  -> SandboxSpec
 *   - per-run llm_* columns                            -> Connection
 *   - core/agents/features.py + memory presets         -> Capability / MemoryPreset
 *
 * Sub-agent topology is a strict star of depth 1: a lead delegates tasks via the
 * `task` tool to sub-agents (currently one registry type: general-purpose). There
 * is NO "skills" system in the backend — the honest capabilities are sub-agent
 * types, the sandbox toolset, RuntimeFeatures flags and memory presets.
 *
 * Narrative + endpoints: docs/API_CONTRACT.md. Machine-readable: docs/openapi.yaml.
 */

// ── run status machine (core/runtime/schemas.py::LEGAL_TRANSITIONS) ───────────

export type RunStatus = "pending" | "running" | "succeeded" | "failed" | "interrupted";

export const TERMINAL_STATUSES: readonly RunStatus[] = ["succeeded", "failed", "interrupted"];
export const ACTIVE_STATUSES: readonly RunStatus[] = ["pending", "running"];

export function isTerminal(s: RunStatus): boolean {
  return TERMINAL_STATUSES.includes(s);
}
export function isActive(s: RunStatus): boolean {
  return ACTIVE_STATUSES.includes(s);
}
/** Resume is legal only from failed/interrupted (→ pending via claim). */
export function isResumable(s: RunStatus): boolean {
  return s === "failed" || s === "interrupted";
}

export type SubmitDisposition = "created" | "resumed" | "already_succeeded" | "attached";
export type StopReason = "orphan_recovered" | "cancelled" | "shutting_down" | null;

// ── sub-agents (core/agents/subagents/) ───────────────────────────────────────

/** SubagentStatus enum from contract.py. Terminal: completed/failed/cancelled/timed_out. */
export type SubagentStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out";

export const SUBAGENT_TERMINAL: readonly SubagentStatus[] = [
  "completed",
  "failed",
  "cancelled",
  "timed_out",
];

/** Additive cap reason (never a new status), from contract.py. */
export type SubagentStopReason = "token_capped" | "turn_capped" | "loop_capped";

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

/** A tool-call receipt a sub-agent must cite in its report (receipts.py). */
export interface ToolReceipt {
  id: string;
  tool: string;
  summary: string;
}

/** Citation verification of a sub-agent's report against its receipts. */
export interface ReceiptVerdict {
  cited: number;
  uncited: number;
  ok: boolean;
}

/** One delegation (lead → sub-agent), the leaf of the star. task_tool.py inputs
 *  + the terminal result metadata (contract.py::StructuredSubagentResult). */
export interface TaskDelegation {
  taskId: string;
  subagentType: string;
  /** 3-5 word progress label. */
  description: string;
  prompt: string;
  status: SubagentStatus;
  stopReason: SubagentStopReason | null;
  error: string | null;
  acceptanceCriteria: string[];
  tokenUsage: TokenUsage | null;
  resultBrief: string | null;
  toolReceipts: ToolReceipt[];
  receiptVerdict: ReceiptVerdict | null;
  startedAt: string | null;
  completedAt: string | null;
}

// ── run ───────────────────────────────────────────────────────────────────────

export interface RunConnection {
  apiBase: string;
  model: string;
  keyMasked: string;
}

export interface RunMetrics {
  /** Nodes/sub-agents currently running. */
  agentsActive: number;
  agentsTotal: number;
  elapsedSec: number;
  /** Cumulative token usage — real now (summed from sub-agent delegations). */
  tokenUsage: TokenUsage | null;
}

export interface Run {
  id: string;
  repositoryId: string;
  repoUrl: string;
  repo: string;
  commitSha: string | null;
  status: RunStatus;
  error: string | null;
  stopReason: StopReason;
  cancelRequestedAt: string | null;
  attempt: number;
  connection: RunConnection;
  sandbox: string | null;
  limits: RunLimits | null;
  memoryPreset: string | null;
  hasReport: boolean;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  updatedAt: string;
  metrics: RunMetrics;
}

/**
 * Advanced run knobs — RuntimeFeatures flags (features.py) + SubagentCapacity +
 * the token budget. Forward config: `subagent` is wired today; `tokenBudget`,
 * `guardrail`, `loopDetection` are declared but not yet wired in the backend
 * (the UI marks them). `token_capped`/`loop_capped` stop_reasons already exist
 * on the sub-agent side, so these knobs have a real destination.
 */
export interface RunFeatures {
  /** RuntimeFeatures.subagent — enable the `task` tool + limit middleware. */
  subagent: boolean;
  /** SubagentCapacity concurrency + lead-side max_concurrent. */
  maxSubagents: number;
  /** SubagentLimitMiddleware: total delegations allowed per run. */
  maxTotalSubagents: number;
  /** Per-run token budget (token_budget feature). null = unlimited. */
  tokenBudget: number | null;
  /** RuntimeFeatures.guardrail — planned. */
  guardrail: boolean;
  /** RuntimeFeatures.loop_detection — planned. */
  loopDetection: boolean;
  /** Per-subagent execution timeout, seconds. null = type default (600s). */
  subagentTimeout: number | null;
  /** Wait for a free capacity slot, seconds. null = default (300s). */
  queueTimeout: number | null;
}

export const DEFAULT_RUN_FEATURES: RunFeatures = {
  subagent: true,
  maxSubagents: 4,
  maxTotalSubagents: 6,
  tokenBudget: null,
  guardrail: false,
  loopDetection: false,
  subagentTimeout: null,
  queueTimeout: null,
};

/** Per-run limits persisted on the run (subset of RunFeatures honored today). */
export interface RunLimits {
  subagent?: boolean;
  maxSubagents?: number;
  maxTotalSubagents?: number;
  tokenBudget?: number | null;
  loopDetection?: boolean;
  /** Per-subagent execution timeout, seconds (null/omit = type default 600s). */
  subagentTimeout?: number | null;
  /** Wait for a free capacity slot, seconds (null/omit = default 300s). */
  queueTimeout?: number | null;
}

export interface SubmitRunRequest {
  repoUrl: string;
  branch?: string;
  /** pipeline (default) | agent — lead with sub-agent delegation. */
  mode?: "pipeline" | "agent";
  /** User task for the run (agent mode; "{repo_url}" is substituted). */
  instructions?: string;
  connectionId?: string;
  model?: string;
  apiBase?: string;
  apiKey?: string;
  sandbox?: string;
  memoryPreset?: string;
  features?: RunFeatures;
}

export interface SubmitRunResponse {
  run: Run;
  disposition: SubmitDisposition;
}

// ── report (core/agents/nodes.py::report output) ──────────────────────────────

export interface ReportModule {
  path: string;
  docstring: string | null;
  classes: string[];
  functions: string[];
}

export interface ReportStructure {
  fileCount: number;
  totalBytes: number;
  truncated: boolean;
  languages: Record<string, number>;
  keyFiles: string[];
  files: string[];
}

export type Severity = "critical" | "high" | "medium" | "low" | "info";

/** A security finding recorded in agent security-review mode. */
export interface Finding {
  title: string;
  severity: Severity;
  description: string;
  file: string | null;
  startLine: number | null;
  endLine: number | null;
  cwe: string | null;
  cve: string | null;
  impact: string | null;
  evidence: string | null;
  remediation: string | null;
  confidence: string | null;
  /** Who found it — "lead" or a sub-agent type. */
  agent?: string;
}

export interface ReportMeta {
  severityCounts: Record<Severity, number>;
  total: number;
  agents: string[];
  toolCalls: number;
  filesReviewed: number;
}

export interface Report {
  repoUrl: string;
  commit: string;
  description: string;
  structure: ReportStructure;
  modules: ReportModule[];
  dependencies: string[];
  skippedFiles: string[];
  /** Present in agent security-review runs. */
  findings?: Finding[];
  summary?: string;
  meta?: ReportMeta;
  error?: string;
}

// ── run graph (procedural pipeline nodes + lead/sub-agent star) ───────────────

export type NodeStatus = "pending" | "running" | "completed" | "error";
/** procedural = pure code node (scan/report); agent = lead / sub-agent. */
export type NodeKind = "procedural" | "agent";

export interface GraphNode {
  id: string;
  label: string;
  kind: NodeKind;
  status: NodeStatus;
  /** Lead id for a delegated sub-agent (star topology); null for graph nodes. */
  parentId: string | null;
  x?: number;
  y?: number;
  // ── sub-agent runtime (present on delegated sub-agent nodes) ──
  subagentType?: string;
  /** The task's 3-5 word label. */
  description?: string;
  tokenUsage?: TokenUsage | null;
  stopReason?: SubagentStopReason | null;
  subStatus?: SubagentStatus;
  // ── lead runtime (present on the lead node in agent runs) ──
  toolCalls?: number;
  findings?: number;
}

export interface GraphEdge {
  from: string;
  to: string;
  conditional?: boolean;
}

export interface RunGraph {
  runId: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ── node spec (inspector source) ──────────────────────────────────────────────

export interface ToolSpec {
  name: string;
  description: string;
  signature?: string;
}

/**
 * Static description of a node. Procedural nodes: systemPrompt is the real inline
 * prompt (parse's _DESCRIBE_PROMPT) or null, tools = the sandbox commands. Lead:
 * has the sandbox toolset + the `task` tool. Sub-agent nodes: the registry type
 * (systemPrompt, sandbox toolset, maxTurns, timeoutSeconds).
 */
export interface NodeSpec {
  id: string;
  label: string;
  kind: NodeKind;
  description: string;
  systemPrompt: string | null;
  tools: ToolSpec[];
  model: string | null;
  memoryPreset: string | null;
  /** Present for lead/sub-agent nodes. */
  subagentType?: string;
  maxTurns?: number;
  timeoutSeconds?: number;
  /** The delegation runtime for a sub-agent node (null for lead/procedural). */
  delegation?: TaskDelegation | null;
}

// ── event stream (run_events + task_* custom stream) ──────────────────────────

export type RunEventType =
  | "node_update" // LangGraph "updates" chunk: a pipeline node produced output
  | "custom" // other custom stream chunk
  | "task_started" // sub-agent delegation began
  | "task_running" // sub-agent progress step
  | "task_completed"
  | "task_failed"
  | "task_cancelled"
  | "task_timed_out"
  | "status" // run status changed
  | "log"
  | "gap"; // StreamGap

/** A persisted post-run chat turn (user question or agent answer). */
export interface ChatTurn {
  role: "user" | "agent";
  text: string;
}

export interface RunEvent {
  cursor: number;
  ts: string;
  type: RunEventType;
  /** Node id ("scan"/"parse"/"report") or sub-agent task_id this event belongs to. */
  agent?: string;
  level?: "info" | "warn" | "error";
  message?: string;
  data?: RunEventData;
}

export type RunEventData =
  | { kind: "node_status"; node: string; status: NodeStatus }
  | { kind: "status"; status: RunStatus }
  | { kind: "task_started"; taskId: string; subagentType: string; description: string }
  | {
      kind: "task_step";
      taskId: string;
      messageIndex: number;
      frameKind: "ai" | "tool";
      text: string;
      toolName?: string;
      toolCalls?: { name: string; args: string }[];
    }
  | {
      kind: "task_terminal";
      taskId: string;
      subagentType: string;
      status: SubagentStatus;
      stopReason: SubagentStopReason | null;
      error: string | null;
      usage: TokenUsage | null;
    }
  | {
      kind: "agent_step";
      node: string;
      text: string;
      toolCalls: { name: string; args: string }[];
      toolResults: string[];
    };

// ── connections ────────────────────────────────────────────────────────────────

export interface Connection {
  id: string;
  name: string;
  apiBase: string;
  model: string;
  keyMasked: string;
  createdAt: string;
  lastCheck: { ok: boolean; latencyMs: number; at: string } | null;
}

// ── sandboxes ──────────────────────────────────────────────────────────────────

export type SandboxKind = "opensandbox" | "local" | "ssh";

export interface SandboxSpec {
  id: string;
  name: string;
  kind: SandboxKind;
  image: string | null;
  workdir: string | null;
  createdAt: string;
  runCount: number;
}

export type SandboxInstanceStatus = "alive" | "dead";

/**
 * A provisioned sandbox (not a preset): created without TTL, lives past the run
 * that made it until killed by hand. Resume reconnects to a live instance by id.
 */
export interface SandboxInstance {
  id: string;
  externalId: string;
  kind: string;
  image: string | null;
  runId: string | null;
  status: SandboxInstanceStatus;
  createdAt: string;
  killedAt: string | null;
}

// ── capabilities catalog (honest: no "skills" system exists) ──────────────────

/**
 * The real, browsable "capabilities" of the system:
 *  - subagent    → a registry sub-agent type (registry.py)
 *  - tool        → a sandbox tool (tools.py)
 *  - capability  → a RuntimeFeatures flag (features.py)
 *  - memory_preset → a MemoryConfig (memory/presets.py)
 * `active` = wired into the run/agent path today.
 */
export type CapabilitySource = "subagent" | "tool" | "capability" | "memory_preset";

export interface Capability {
  id: string;
  name: string;
  description: string;
  source: CapabilitySource;
  active: boolean;
  body: string;
  /** Node/agent ids or types that use it. */
  usedBy: string[];
  tags: string[];
}

export interface MemoryPreset {
  name: string;
  description: string;
  production: boolean;
}

// ── list responses & errors ───────────────────────────────────────────────────

export interface RunListResponse {
  runs: Run[];
}

export interface ApiError {
  error: { code: string; message: string };
}
