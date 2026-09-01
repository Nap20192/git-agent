/**
 * Demo fixtures for the mock adapter. Grounded in the REAL backend at HEAD
 * (master 68a7c56), including core/agents/subagents/. Seeds:
 *   - a live 3-node pipeline run (scan → parse → report), procedural nodes, and
 *   - an example lead + sub-agent run: a lead delegates tasks via the `task` tool
 *     to `general-purpose` sub-agents (star, depth 1) with the real system prompt,
 *     the fixed sandbox toolset, real token usage and tool receipts.
 *
 * There is no "skills" system in the backend; the capabilities catalog surfaces
 * the real things: sub-agent types, the sandbox tools, RuntimeFeatures and presets.
 */
import type {
  Capability,
  Connection,
  GraphEdge,
  GraphNode,
  MemoryPreset,
  NodeSpec,
  Report,
  Run,
  RunEvent,
  SandboxSpec,
  TaskDelegation,
  ToolSpec,
  TokenUsage,
} from "./contract.ts";

export const LIVE_RUN_ID = "run-1042";
export const AGENT_RUN_ID = "run-1039";

// ── sandboxes (migrations/003_sandboxes.sql seed) ─────────────────────────────

export const SANDBOXES: SandboxSpec[] = [
  { id: "sbx-git", name: "git", kind: "opensandbox", image: "alpine/git:latest", workdir: null, createdAt: "2026-08-20T10:00:00Z", runCount: 34 },
  { id: "sbx-python", name: "python", kind: "opensandbox", image: "python:3.12-slim", workdir: null, createdAt: "2026-08-20T10:00:00Z", runCount: 21 },
  { id: "sbx-local", name: "local", kind: "local", image: null, workdir: "/tmp/git-agent-work", createdAt: "2026-08-20T10:00:00Z", runCount: 8 },
];

export const CONNECTIONS: Connection[] = [
  { id: "conn-anthropic", name: "anthropic", apiBase: "https://api.anthropic.com/v1", model: "claude-opus-4", keyMasked: "sk-ant-••••••••••8fT2", createdAt: "2026-08-21T09:00:00Z", lastCheck: { ok: true, latencyMs: 310, at: "2026-09-01T12:00:00Z" } },
  { id: "conn-openai", name: "openai", apiBase: "https://api.openai.com/v1", model: "gpt-4o", keyMasked: "sk-••••••••••••dQ9", createdAt: "2026-08-22T11:00:00Z", lastCheck: { ok: true, latencyMs: 280, at: "2026-08-31T18:00:00Z" } },
  { id: "conn-ollama", name: "ollama-local", apiBase: "http://localhost:11434/v1", model: "qwen2.5-coder:14b", keyMasked: "— local —", createdAt: "2026-08-25T14:00:00Z", lastCheck: { ok: false, latencyMs: 0, at: "2026-08-30T08:00:00Z" } },
];

export const MEMORY_PRESETS: MemoryPreset[] = [
  { name: "full_history", description: "No compaction — keep the entire message history.", production: false },
  { name: "prod", description: "Production default: summarization + tool-output clearing.", production: true },
  { name: "prod_v2", description: "Production for long-context providers.", production: true },
  { name: "aggressive", description: "Tight token budget: early summarization, small keep window.", production: false },
  { name: "sliding_window", description: "Keep the last N messages, drop older turns.", production: false },
];

// ── the real toolset (core/agents/tools.py) ───────────────────────────────────

const SANDBOX_TOOLS: ToolSpec[] = [
  { name: "sandbox_run", description: "Run a shell command in the isolated sandbox with the cloned repo. Returns stdout (or error text on non-zero exit).", signature: "sandbox_run(command: str) -> str" },
  { name: "read_file", description: "Read a text file from the sandbox by absolute path.", signature: "read_file(path: str) -> str" },
];

const TASK_TOOL: ToolSpec = {
  name: "task",
  description: "Delegate a self-contained task to a sub-agent with an isolated context (star, depth 1). Sub-agents do not have this tool.",
  signature: "task(description, prompt, subagent_type, acceptance_criteria?) -> report",
};

// The real general-purpose sub-agent system prompt (registry.py::_GENERAL_PURPOSE_PROMPT).
const GENERAL_PURPOSE_PROMPT = `You are a subagent: a focused worker executing ONE delegated task inside an isolated context. You operate on a git repository cloned inside a sandbox; use your tools (sandbox_run, read_file) to investigate and act.

Rules:
- You are a subagent — the \`task\` tool is NOT available to you; never attempt to delegate further. Do all the work yourself.
- Stay strictly within the delegated task. Do not expand scope.
- Your context is disposable; only your final report survives. Make it self-contained: the delegating agent sees nothing else.

Final report contract (5 points):
1. Answer the delegated question directly, first.
2. Cite receipt ids for every action claim.
3. Attach verifiable handles (absolute paths, exact commands) to findings.
4. List what failed or remains uncertain.
5. Be dense: facts over narration; the delegating agent pays for every token.`;

const LEAD_PROMPT = `You are the lead agent for a repository-understanding run. Investigate the cloned repository using your sandbox tools, and delegate self-contained research to \`general-purpose\` sub-agents via the \`task\` tool when the benefit exceeds the overhead (parallel independent work, or heavy research whose intermediate context you don't need). Do NOT delegate merely because a task is multi-step. Synthesize the sub-agents' reports yourself — a sub-agent report is a self-report, so spot-check its verifiable handles.`;

// ── capabilities catalog (all real) ───────────────────────────────────────────

export const CAPABILITIES: Capability[] = [
  { id: "sub-general-purpose", name: "general-purpose", source: "subagent", active: true, tags: ["subagent", "registry"], usedBy: ["lead"], description: "General-purpose research worker with sandbox tools for investigating the cloned repo. max_turns 50, timeout 600s.", body: "registry.py::GENERAL_PURPOSE. The only builtin sub-agent type. One fixed toolset (sandbox_run, read_file); model inherited from the lead; no `task` tool (star depth 1). Returns a self-contained report following the 5-point report contract." },
  { id: "tool-sandbox-run", name: "sandbox_run", source: "tool", active: true, tags: ["sandbox"], usedBy: ["lead", "general-purpose"], description: "Run a shell command in the isolated sandbox.", body: "tools.py::sandbox_run. Output clipped to 50k chars; non-zero exit returns model-readable error text, not an exception." },
  { id: "tool-read-file", name: "read_file", source: "tool", active: true, tags: ["sandbox"], usedBy: ["lead", "general-purpose"], description: "Read a file from the sandbox by absolute path.", body: "tools.py::read_file." },
  { id: "cap-subagent", name: "subagent", source: "capability", active: true, tags: ["orchestration"], usedBy: ["lead"], description: "Enable the `task` tool + SubagentLimitMiddleware.", body: "RuntimeFeatures.subagent=True → wires SubagentLimitMiddleware (cuts task calls at the cap, finish_reason=stop). Admission via SubagentCapacity (FIFO). ACTIVE — the sub-agent system landed on master." },
  { id: "cap-sandbox", name: "sandbox", source: "capability", active: true, tags: ["runtime"], usedBy: ["scan", "parse", "report", "general-purpose"], description: "Execute untrusted repo operations inside an isolated sandbox.", body: "RuntimeFeatures.sandbox — every run's tools shell into the Sandbox port (opensandbox/local/ssh)." },
  { id: "cap-memory", name: "memory", source: "capability", active: true, tags: ["context"], usedBy: ["lead"], description: "Context-management middleware from the memory preset.", body: "RuntimeFeatures.memory — summarization + context editing driven by the resolved preset." },
  { id: "cap-guardrail", name: "guardrail", source: "capability", active: false, tags: ["safety"], usedBy: [], description: "Input/output guardrail middleware.", body: "RuntimeFeatures.guardrail — no builtin middleware yet; pass a custom AgentMiddleware." },
  { id: "cap-loop-detection", name: "loop_detection", source: "capability", active: false, tags: ["safety"], usedBy: [], description: "Detect and break agent loops.", body: "RuntimeFeatures.loop_detection — not wired yet (loop_capped stop_reason exists on the sub-agent side)." },
  { id: "cap-token-budget", name: "token_budget", source: "capability", active: false, tags: ["cost"], usedBy: [], description: "Enforce a per-run token budget.", body: "RuntimeFeatures.token_budget — not wired (token_capped stop_reason exists on the sub-agent side)." },
  { id: "cap-vision", name: "vision", source: "capability", active: false, tags: [], usedBy: [], description: "Vision/image input support.", body: "RuntimeFeatures.vision — not wired yet." },
  { id: "preset-prod-v2", name: "prod_v2", source: "memory_preset", active: true, tags: ["context"], usedBy: ["lead"], description: "Production long-context compaction preset.", body: "core/memory/presets.py. Part of run experiment identity by name." },
  { id: "preset-prod", name: "prod", source: "memory_preset", active: true, tags: ["context"], usedBy: [], description: "Production default compaction preset.", body: "core/memory/presets.py." },
];

// ── graphs ─────────────────────────────────────────────────────────────────────

function pipelineNodes(): GraphNode[] {
  return [
    { id: "scan", label: "scan", kind: "procedural", status: "pending", parentId: null, x: 50, y: 18 },
    { id: "parse", label: "parse", kind: "procedural", status: "pending", parentId: null, x: 50, y: 50 },
    { id: "report", label: "report", kind: "procedural", status: "pending", parentId: null, x: 50, y: 82 },
  ];
}
const PIPELINE_EDGES: GraphEdge[] = [
  { from: "scan", to: "parse" },
  { from: "parse", to: "report" },
  { from: "scan", to: "report", conditional: true },
];

// Lead + general-purpose sub-agent star (depth 1). Each leaf is a `task` delegation.
const USAGE = (i: number, o: number): TokenUsage => ({ inputTokens: i, outputTokens: o, totalTokens: i + o });

const DELEGATIONS: Record<string, TaskDelegation> = {
  "task-structure": {
    taskId: "task-structure", subagentType: "general-purpose", description: "map repo structure", status: "completed", stopReason: null, error: null,
    prompt: "Map the repository at the sandbox repo dir: enumerate files, classify by extension, and list key files (README, manifests, Dockerfile). Report counts and key paths. Do not read code semantics.",
    acceptanceCriteria: ["file count reported", "languages by extension", "key files listed with absolute paths"],
    tokenUsage: USAGE(8200, 1400), resultBrief: "143 files, 68 .py; key files: README.md, pyproject.toml, CLAUDE.md, docker-compose.yml.",
    toolReceipts: [{ id: "r1", tool: "sandbox_run", summary: "find . -type f | wc -l → 143" }, { id: "r2", tool: "sandbox_run", summary: "ls key files" }],
    receiptVerdict: { cited: 2, uncited: 0, ok: true }, startedAt: "2026-09-01T12:03:03Z", completedAt: "2026-09-01T12:03:09Z",
  },
  "task-modules": {
    taskId: "task-modules", subagentType: "general-purpose", description: "parse modules", status: "completed", stopReason: null, error: null,
    prompt: "For the Python modules in the repo, extract classes, top-level functions and module docstrings via the AST. Emit a compact structured summary per module. Cite the exact files you read.",
    acceptanceCriteria: ["per-module classes/functions", "docstrings where present", "receipt ids cited"],
    tokenUsage: USAGE(12400, 2600), resultBrief: "core/agents/nodes.py → scan/parse/report; runtime.py → Runtime; config.py → Settings.",
    toolReceipts: [{ id: "r3", tool: "read_file", summary: "read core/agents/nodes.py" }, { id: "r4", tool: "read_file", summary: "read core/runtime/runtime.py" }],
    receiptVerdict: { cited: 2, uncited: 1, ok: true }, startedAt: "2026-09-01T12:03:04Z", completedAt: "2026-09-01T12:03:12Z",
  },
  "task-deps": {
    taskId: "task-deps", subagentType: "general-purpose", description: "audit deps", status: "completed", stopReason: "turn_capped", error: null,
    prompt: "Locate and parse dependency manifests (pyproject.toml, requirements.txt). Produce the list of direct dependencies with versions where pinned.",
    acceptanceCriteria: ["manifests located", "direct deps listed"],
    tokenUsage: USAGE(5100, 900), resultBrief: "langchain>=1.0, langgraph>=1.0, langfuse, pydantic-settings, psycopg[binary]. (capped: turn budget)",
    toolReceipts: [{ id: "r5", tool: "sandbox_run", summary: "cat pyproject.toml" }],
    receiptVerdict: { cited: 1, uncited: 0, ok: true }, startedAt: "2026-09-01T12:03:05Z", completedAt: "2026-09-01T12:03:11Z",
  },
};

function agentNodes(): GraphNode[] {
  const leaf = (id: string, x: number): GraphNode => {
    const d = DELEGATIONS[id];
    return { id, label: d.description, kind: "agent", status: "completed", parentId: "lead", x, y: 46, subagentType: "general-purpose", description: d.description, tokenUsage: d.tokenUsage, stopReason: d.stopReason, subStatus: d.status };
  };
  return [
    { id: "lead", label: "lead", kind: "agent", status: "completed", parentId: null, x: 50, y: 12 },
    leaf("task-structure", 22),
    leaf("task-modules", 50),
    leaf("task-deps", 78),
    { id: "report", label: "report", kind: "procedural", status: "completed", parentId: null, x: 50, y: 84 },
  ];
}
const AGENT_EDGES: GraphEdge[] = [
  { from: "lead", to: "task-structure" },
  { from: "lead", to: "task-modules" },
  { from: "lead", to: "task-deps" },
  { from: "task-structure", to: "report" },
  { from: "task-modules", to: "report" },
  { from: "task-deps", to: "report" },
];

export function graphFor(runId: string): { nodes: GraphNode[]; edges: GraphEdge[] } {
  if (runId === AGENT_RUN_ID) return { nodes: agentNodes(), edges: AGENT_EDGES };
  return { nodes: pipelineNodes(), edges: PIPELINE_EDGES };
}

// ── node specs (inspector source) ──────────────────────────────────────────────

const DESCRIBE_PROMPT = `Ты разбираешь git-репозиторий. По данным ниже опиши в 3-6 предложениях,
что делает проект и из каких основных частей он состоит. Отвечай только описанием.

Ключевые файлы: {key_files}
Статистика по расширениям: {languages}
Модули Python (путь, классы, функции):
{modules}`;

const PIPELINE_SPECS: Record<string, NodeSpec> = {
  scan: {
    id: "scan", label: "scan", kind: "procedural", model: null, memoryPreset: null,
    description: "Clones the repo at --depth 1 into the sandbox, resolves HEAD, and lists files (skipping .git/node_modules/__pycache__/…), capping at 5000 files.",
    systemPrompt: null,
    tools: [
      { name: "git clone", description: "Shallow-clone the target repository.", signature: "git clone --depth 1 <repo_url> <repo_dir>" },
      { name: "git rev-parse", description: "Resolve the checked-out commit.", signature: "git -C <repo_dir> rev-parse HEAD" },
      { name: "find + stat", description: "Enumerate files with sizes.", signature: "find . -type f -exec stat -c '%s %n' {} \\;" },
    ],
  },
  parse: {
    id: "parse", label: "parse", kind: "procedural", model: "claude-opus-4", memoryPreset: null,
    description: "AST-parses up to 40 Python files (≤80KB), reads dependency manifests, then makes ONE LLM call with the describe-prompt.",
    systemPrompt: DESCRIBE_PROMPT,
    tools: [
      { name: "ast.parse", description: "Extract classes/functions/docstring per module.", signature: "ast.parse(source)" },
      { name: "read manifests", description: "Read pyproject.toml / requirements.txt dependencies.", signature: "tomllib.loads(...)" },
      { name: "model.ainvoke", description: "One LLM call for the project description.", signature: "model.ainvoke(_DESCRIBE_PROMPT)" },
    ],
  },
  report: {
    id: "report", label: "report", kind: "procedural", model: null, memoryPreset: null,
    description: "Assembles the final Report JSON from scan + parse results.",
    systemPrompt: null,
    tools: [{ name: "assemble", description: "Merge scan+parse state into the Report shape.", signature: "report = {...}" }],
  },
};

const AGENT_SPECS: Record<string, NodeSpec> = {
  lead: {
    id: "lead", label: "lead", kind: "agent", model: "claude-opus-4", memoryPreset: "prod_v2", subagentType: undefined, maxTurns: undefined, timeoutSeconds: undefined,
    description: "The lead agent: investigates the repo and delegates self-contained tasks to general-purpose sub-agents via the `task` tool, then synthesizes their reports.",
    systemPrompt: LEAD_PROMPT,
    tools: [...SANDBOX_TOOLS, TASK_TOOL],
    delegation: null,
  },
  report: {
    id: "report", label: "report", kind: "procedural", model: null, memoryPreset: null,
    description: "Assembles the final Report from the lead's synthesis.",
    systemPrompt: null,
    tools: [{ name: "assemble", description: "Merge into the Report shape.", signature: "report = {...}" }],
  },
};

function subagentSpec(taskId: string): NodeSpec {
  const d = DELEGATIONS[taskId];
  return {
    id: taskId, label: d.description, kind: "agent", model: "claude-sonnet-4", memoryPreset: "prod",
    subagentType: "general-purpose", maxTurns: 50, timeoutSeconds: 600,
    description: `general-purpose sub-agent delegated: "${d.description}". Isolated context; returns only its report.`,
    systemPrompt: GENERAL_PURPOSE_PROMPT,
    tools: SANDBOX_TOOLS,
    delegation: d,
  };
}

export function nodeSpec(runId: string, nodeId: string): NodeSpec | null {
  if (runId === AGENT_RUN_ID) {
    if (AGENT_SPECS[nodeId]) return AGENT_SPECS[nodeId];
    if (DELEGATIONS[nodeId]) return subagentSpec(nodeId);
    return null;
  }
  return PIPELINE_SPECS[nodeId] ?? null;
}

// ── reports ────────────────────────────────────────────────────────────────────

function sampleReport(repoUrl: string, commit: string): Report {
  return {
    repoUrl, commit,
    description:
      "git-agent is an agentic system that turns a git repository into structured knowledge. It clones the target into a sandbox, walks the file tree, AST-parses Python modules, reads dependency manifests, and asks an LLM for a short project description. A durable runtime treats each run as a resumable resource with leases, checkpoints and a replayable event stream; a lead agent can delegate research to general-purpose sub-agents via the task tool.",
    structure: {
      fileCount: 143, totalBytes: 512_400, truncated: false,
      languages: { ".py": 68, ".md": 12, ".sql": 4, ".toml": 2, ".lean": 1, "(none)": 9 },
      keyFiles: ["README.md", "pyproject.toml", "CLAUDE.md", "docker-compose.yml"],
      files: ["main.py", "core/agents/graph.py", "core/agents/nodes.py", "core/agents/subagents/task_tool.py", "core/runtime/runtime.py"],
    },
    modules: [
      { path: "core/agents/nodes.py", docstring: "Узлы графа Рана: scan → parse → report.", classes: [], functions: ["scan", "parse", "report"] },
      { path: "core/agents/subagents/task_tool.py", docstring: "Тул `task` — единственный вход в систему сабагентов.", classes: [], functions: ["build_task_tool"] },
      { path: "core/runtime/runtime.py", docstring: "Durable run runtime — a run is a resource.", classes: ["Runtime"], functions: ["submit", "cancel", "events"] },
    ],
    dependencies: ["langchain>=1.0", "langgraph>=1.0", "langfuse", "pydantic-settings", "psycopg[binary]"],
    skippedFiles: ["core/generated/pb2.py"],
  };
}

export const REPORTS: Record<string, Report> = {
  [AGENT_RUN_ID]: sampleReport("github.com/vnkjd/git-agent", "68a7c56"),
  "run-1035": sampleReport("github.com/acme/auth-service", "9a3f1c2"),
  "run-1031": sampleReport("github.com/acme/web-frontend", "4b8e0aa"),
};

// ── static event log for the completed lead+sub-agent run ─────────────────────

export function agentRunEvents(): RunEvent[] {
  const t = "2026-09-01T12:03:";
  const seq: Omit<RunEvent, "cursor">[] = [
    { ts: `${t}01Z`, type: "log", agent: "lead", level: "info", message: "lead planning · target github.com/vnkjd/git-agent @ main" },
    { ts: `${t}03Z`, type: "task_started", agent: "task-structure", message: "task started · map repo structure", data: { kind: "task_started", taskId: "task-structure", subagentType: "general-purpose", description: "map repo structure" } },
    { ts: `${t}04Z`, type: "task_started", agent: "task-modules", message: "task started · parse modules", data: { kind: "task_started", taskId: "task-modules", subagentType: "general-purpose", description: "parse modules" } },
    { ts: `${t}05Z`, type: "task_started", agent: "task-deps", message: "task started · audit deps", data: { kind: "task_started", taskId: "task-deps", subagentType: "general-purpose", description: "audit deps" } },
    { ts: `${t}07Z`, type: "task_running", agent: "task-structure", message: "sandbox_run: find . -type f", data: { kind: "task_step", taskId: "task-structure", messageIndex: 1, frameKind: "tool", text: "143", toolName: "sandbox_run" } },
    { ts: `${t}08Z`, type: "task_running", agent: "task-modules", message: "read_file core/agents/nodes.py", data: { kind: "task_step", taskId: "task-modules", messageIndex: 1, frameKind: "ai", text: "reading modules", toolCalls: [{ name: "read_file", args: '{"path":"core/agents/nodes.py"}' }] } },
    { ts: `${t}09Z`, type: "task_completed", agent: "task-structure", message: "completed · 9.6k tokens", data: { kind: "task_terminal", taskId: "task-structure", subagentType: "general-purpose", status: "completed", stopReason: null, error: null, usage: { inputTokens: 8200, outputTokens: 1400, totalTokens: 9600 } } },
    { ts: `${t}11Z`, type: "task_completed", agent: "task-deps", message: "completed (capped: turn budget) · 6.0k tokens", data: { kind: "task_terminal", taskId: "task-deps", subagentType: "general-purpose", status: "completed", stopReason: "turn_capped", error: null, usage: { inputTokens: 5100, outputTokens: 900, totalTokens: 6000 } } },
    { ts: `${t}12Z`, type: "task_completed", agent: "task-modules", message: "completed · 15.0k tokens", data: { kind: "task_terminal", taskId: "task-modules", subagentType: "general-purpose", status: "completed", stopReason: null, error: null, usage: { inputTokens: 12400, outputTokens: 2600, totalTokens: 15000 } } },
    { ts: `${t}15Z`, type: "log", agent: "lead", level: "info", message: "synthesizing 3 sub-agent reports · spot-checking handles" },
    { ts: `${t}18Z`, type: "node_update", agent: "report", message: "report assembled · 143 files · 3 modules" },
    { ts: `${t}19Z`, type: "status", agent: "report", message: "succeeded", data: { kind: "status", status: "succeeded" } },
  ];
  return seq.map((e, i) => ({ ...e, cursor: i + 1 }));
}

/** Cumulative token usage for the agent run (sum of delegations). */
export const AGENT_RUN_USAGE: TokenUsage = USAGE(25700, 4900);

// ── runs (the list) ────────────────────────────────────────────────────────────

function baseRun(over: Partial<Run> & Pick<Run, "id" | "repo" | "status">): Run {
  const conn = CONNECTIONS[0];
  return {
    repositoryId: "repo-x", repoUrl: `github.com/${over.repo}`, commitSha: "a1b2c3d",
    error: null, stopReason: null, cancelRequestedAt: null, attempt: 1,
    connection: { apiBase: conn.apiBase, model: conn.model, keyMasked: conn.keyMasked },
    sandbox: "python", memoryPreset: "prod_v2", hasReport: over.status === "succeeded",
    createdAt: "2026-09-01T11:00:00Z", startedAt: "2026-09-01T11:00:01Z",
    finishedAt: over.status === "running" || over.status === "pending" ? null : "2026-09-01T11:04:00Z",
    updatedAt: "2026-09-01T11:04:00Z",
    metrics: { agentsActive: 0, agentsTotal: 3, elapsedSec: 214, tokenUsage: null },
    ...over,
  };
}

export function historicalRuns(): Run[] {
  return [
    baseRun({ id: AGENT_RUN_ID, repo: "vnkjd/git-agent", status: "succeeded", commitSha: "68a7c56", memoryPreset: "prod_v2", metrics: { agentsActive: 0, agentsTotal: 5, elapsedSec: 186, tokenUsage: AGENT_RUN_USAGE } }),
    baseRun({ id: "run-1035", repo: "acme/auth-service", status: "succeeded", metrics: { agentsActive: 0, agentsTotal: 3, elapsedSec: 141, tokenUsage: null } }),
    baseRun({ id: "run-1031", repo: "acme/web-frontend", status: "succeeded", metrics: { agentsActive: 0, agentsTotal: 3, elapsedSec: 98, tokenUsage: null } }),
    baseRun({ id: "run-1029", repo: "acme/notification-svc", status: "interrupted", stopReason: "cancelled", hasReport: false, metrics: { agentsActive: 0, agentsTotal: 3, elapsedSec: 52, tokenUsage: null } }),
    baseRun({ id: "run-1024", repo: "acme/data-pipeline", status: "failed", attempt: 2, hasReport: false, error: "clone timed out after 180s", metrics: { agentsActive: 0, agentsTotal: 3, elapsedSec: 181, tokenUsage: null } }),
    baseRun({ id: "run-1018", repo: "acme/mobile-gateway", status: "pending", startedAt: null, finishedAt: null, hasReport: false, metrics: { agentsActive: 0, agentsTotal: 3, elapsedSec: 0, tokenUsage: null } }),
  ];
}

export const LIVE_REPO = "acme/payments-api";
