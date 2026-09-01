# git-agent frontend — product IA & interaction design

Pivot the vulnhunt mock into the real product: a UI over the git-agent runtime
(LangGraph `scan → parse → report`, durable Runs, Reports, sandboxes, per-run LLM
connections). Keep the terminal aesthetic (dark monochrome, amber accent), keep the
architecture (`api → hooks → app → features`), keep the primitives. Delete the fantasy.

**Grounding sources** (everything below is checked against these):
`CONTEXT.md` (glossary), `core/runtime/schemas.py` (status machine),
`core/agents/graph.py` + `nodes.py` (the real graph), `core/agents/factory.py`
(`build_agent(model, tools, system_prompt, middleware)`),
`core/agents/middleware/history.py` (`run_events` kinds), `migrations/*.sql`
(runs / run_events / sandboxes tables), `core/agents/llm.py` + `core/config.py`
(LLM connection), `infra/sandboxes.py` (sandbox kinds), `core/memory/presets.py`
(memory presets).

**Honesty legend** used throughout:
- ✅ **renderable** — data exists in the backend today (maybe behind a missing-but-trivial HTTP endpoint).
- 🔶 **thin backend** — data exists (table/state), needs a small endpoint or field.
- 🔴 **needs backend** — the concept does not exist in the backend yet.

---

## 1. Information architecture

### What the glossary dictates

The domain nouns are: **Repository**, **Run** (one per `(repo, commit, model)`,
resumable, terminal statuses absorbing), **Report** (the product of a Run, 1:1),
**Sandbox** (named, kinds `opensandbox | local | ssh`), **Memory preset**,
plus the run-scoped **graph** and **event stream**. Findings, severities, CWEs,
exploit chains — all fantasy; they map to nothing and get deleted.

Because Report is strictly 1:1 with a Run, **Reports do not get their own collection
screen** — "browse reports" *is* "browse runs filtered to succeeded". One list, one
filter chip. This kills a whole screen and its nav slot.

Repositories similarly stay a **facet of the runs list** (group-by-repo toggle), not a
screen, in v1. Add `/repos` only when someone actually asks "show me everything we know
about repo X across commits".

### Route map

| # | Route | Screen | Replaces | Status |
|---|---|---|---|---|
| 1 | `/runs` | **Runs list** — the home surface. Filter by status/repo, submit new run. | Dashboard-as-home + RecentRuns | ✅ (needs list endpoint) |
| 2 | `/runs/:id` | **Run detail** — interactive graph + node inspector + event stream. Works for live *and* finished runs (same screen, stream replays from cursor 0). | RunScreen (was singleton "the run") | ✅ core / 🔴 inspector tabs, see §2 |
| 3 | `/runs/:id/report` | **Report** — the extracted knowledge: description, structure, modules, dependencies. Tab within run detail chrome. | ReportScreen (findings) | ✅ `runs.report` JSONB exists |
| 4 | `/connections` | **Connections** — named LLM endpoints (api_base + key + model), list/create/pick-per-run. | ConnectionScreen | 🔴 needs a `connections` table |
| 5 | `/sandboxes` | **Sandboxes** — named sandboxes of 3 kinds, list/create. | SandboxScreen | 🔶 table + seed rows exist |
| 6 | `/skills` | **Skills catalog** — browsable capabilities attachable to agents. | — (new) | 🔴 no backend concept at all |
| 7 | `/dash` | **Dashboard** — re-grounded aggregates (runs by status, tokens, repos, active sandboxes). Demoted from home to overview. | DashboardScreen | 🔶 aggregate endpoint |

`DEFAULT_SCREEN` changes from `/run` to `/runs`. The `ActiveRunContext` concept
survives but is renamed semantically: it's "the run I'm watching", set by visiting
`/runs/:id`, and drives TopBar/StatusBar live readouts exactly as today.

**What dies:** `Finding`, `Severity`, `Confidence`, CWE/CVE, `SeverityTag`,
`severity.ts`, LiveFindings, SeverityFilter, TopWeaknesses, SeverityDistribution.
The severity tones (`crit/high/med/low/info`) in `tokens.css` stay — they're now
status/level tones (`crit`=failed, `low`=succeeded green, `med`=interrupted, etc.).

**Status machine realignment (load-bearing).** The mock invented
`queued/paused/cancelling/cancelled/completed`. The backend's machine
(`schemas.py::LEGAL_TRANSITIONS`) is `pending | running | succeeded | failed |
interrupted`, terminal statuses absorbing, resume = `failed|interrupted → pending`
via claim only. The frontend adopts the backend's names verbatim. "Pause" does not
exist in the backend and the control disappears; the run controls become **cancel**
(→ `cancel_requested_at` mailbox, statuses stay honest) and **resume** (= resubmit;
backend returns `disposition: resumed`). A `cancelRequestedAt` field on Run lets the
UI show a "cancelling…" chip without inventing a status.

---

## 2. Run detail — graph, inspector, event stream

### Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ run header: repo slug · commit sha · model · sandbox · status badge  │
│             [cancel] [resume] [→ report]        tokens · elapsed     │
├──────────────────────────────────────┬───────────────────────────────┤
│                                      │  NODE INSPECTOR (Panel)       │
│   GRAPH CANVAS (Panel, ~60% width)   │  ┌─ tabs ──────────────────┐  │
│                                      │  │overview│prompt│tools│   │  │
│   ○ START                            │  │        skills│events    │  │
│    └─▶ [scan]──────┐(error, dashed)  │  └─────────────────────────┘  │
│         └─▶ [parse]│                 │  …tab content…                │
│              └─▶ [report]◀┘          │                               │
│                   └─▶ ◉ END          │  (empty state: "select a      │
│                                      │   node" when none selected)   │
├──────────────────────────────────────┴───────────────────────────────┤
│ EVENT STREAM (Panel, full width, ~35% height, virtual-scrolled)      │
│ filter: [all ▾] [scan] [parse] [report]   follow: ● live             │
└──────────────────────────────────────────────────────────────────────┘
```

Reuses the current RunScreen skeleton (graph panel + event stream already exist);
the inspector replaces LiveFindings + AssistantPanel on the right.

**Honest scale note:** the real graph today is **3 nodes and one conditional edge**
(`scan → parse → report`, `scan --error--> report`). The interaction design below is
sized for that, but every mechanism (pan, drag, per-node events, inspector) scales
unchanged to the sub-agent future (`build_agent` exists in the backend precisely for
that). Do not import a graph library for 3 nodes — see §4.

### GraphCanvas interactions (concrete)

- **Surface**: one `<svg>` inside a Panel with a `viewBox` transformed by
  `translate(panX, panY)`. Nodes are `<g>` groups (rect + label + StatusDot),
  edges are paths with arrowheads; the conditional error edge is dashed with an
  `err` label.
- **Pan**: pointerdown on empty canvas → `setPointerCapture`, drag moves
  `panX/panY`; cursor `grab/grabbing`. Wheel-zoom is **explicitly out of scope v1**
  (3 nodes fit; add when sub-agent graphs outgrow the panel).
- **Drag a node**: pointerdown on a node → capture, move updates that node's
  `{x,y}` in local layout state. Layout is client-owned: initial positions come from
  a trivial left-to-right auto-layout over the edge list (topological rank → column),
  user positions persist to `localStorage` keyed by the graph's node-id set. No
  backend layout persistence — the contract's `x/y/w` hints stay optional.
- **Select**: click node → selected (amber border, glow), inspector populates.
  Click empty canvas or `Esc` → deselect. Only single-select.
- **Live state**: node tone from status — `queued`→muted, `running`→amber +
  StatusDot pulse, `done`→low (green), `halted/error`→crit. The currently-running
  node also gets the pulsing edge into it. Per-node **event count badge**
  (`Badge tone="muted"`) top-right of each node, incrementing live.
- **Hover coupling**: hover a node → its events highlight in the stream; hover an
  event row → its source node gets a subtle outline. Same `agentId ↔ nodeId` key
  both ways.

### NodeInspector tabs

| Tab | Content | Status |
|---|---|---|
| **overview** | kind/label, status + timing (derived from that node's `agent_start`/`agent_finish` events: started, duration), event count, model used, memory preset. KeyValueList rows. | ✅ derivable from `run_events` + run row |
| **system prompt** | The node's prompt in a CodeBlock. Real basis: `parse` has `_DESCRIBE_PROMPT`; agent-built nodes have `build_agent(system_prompt=…)`. Requires the backend to expose a static **node spec** (see §5 `GraphSpec`). `scan`/`report` are pure code, no prompt — tab shows "no LLM prompt (procedural node)", which is honest and informative. | 🔴 needs backend (small: a registry dict) |
| **tools** | Tool list (name, description, param summary) per node. Real basis: `build_agent(tools=[…])` for agent nodes; for today's procedural nodes the spec can list its sandbox operations (`git clone`, `find`, `cat`) as declared capabilities. Rendered as EntityList rows. | 🔴 needs backend (same registry) |
| **skills** | Skills attached to this agent, linking into `/skills`. | 🔴 needs backend — no concept exists (§3) |
| **events** | The event stream pre-filtered to `agent === node.id`, same row component as the main stream, with `model_message` / `tool_call` payloads expandable into CodeBlock. | ✅ `run_events.kind` ∈ agent_start / model_message / tool_call / agent_finish, all carry the agent |

Tab availability degrades gracefully: prompt/tools/skills tabs render an
"unavailable for this backend" note until `GraphSpec` ships, so the screen ships
before the backend does.

### Event stream ↔ graph binding

The binding key is the event's `agent` field (already in `contract.ts::RunEvent`;
the backend's `run_events.payload` must carry the node name — HistoryMiddleware is
per-agent already, so this is a payload field, not a schema change).

- Stream toolbar: node filter chips (one per graph node, from `RunGraph.nodes`) +
  "all". Clicking a chip = same as selecting the node's events tab, but in the wide
  bottom panel.
- Selecting a node in the canvas does **not** force-filter the main stream (that
  would make the canvas feel modal); it highlights matching rows. Filtering is the
  chips' job, the inspector "events" tab is the focused view.
- Live tail: stream auto-follows (`follow: ● live`); any manual scroll-up pauses
  follow, a "jump to live" chip resumes. Cursor/replay/gap semantics unchanged
  from today's `useRunStream` (they already mirror MemoryStreamBridge honestly).
- `model_message` and `tool_call` rows are collapsed to one line (role + first ~120
  chars) and expand in place to a CodeBlock. `agent_start`/`agent_finish` render as
  dividers, visually grouping a node's burst of activity.

---

## 3. Skills, Connections, Sandboxes

### Connections (`/connections`)

**Real basis**: `core/agents/llm.py::make_model` — one OpenAI-compatible endpoint,
`(api_base, api_key, model)`, resolvable per-run (CLI flags / `LLM_*` env). Every run
row already stores `llm_api_base/llm_api_key/llm_model`. What does **not** exist is a
*named, saved* connection — that's a new `connections` table + CRUD. 🔴 needs backend
(small: one table, one CRUD module, mirror of `sandboxes`).

- **List**: EntityList of connection rows — name, api_base host, model, masked key,
  StatusDot for last-checked reachability. The current ProviderCard visual carries
  over almost unchanged (it already shows endpoint + masked key + models).
- **Detail**: click row → Drawer: KeyValueList (full api_base, model, masked key,
  created), "runs using this connection" mini-list, [check] button — backend pings
  `GET {api_base}/models` and reports ok/latency/error 🔴 (tiny endpoint).
- **Create**: [+ new connection] → same Drawer in form mode: name, api_base,
  api_key (write-only — the API returns only `keyMasked`, never the raw key), model.
  TextInput everywhere, `active` state when valid.
- **Run submit integration**: LaunchModal grows a connection select (default =
  backend default from env). Per-run *override* fields (raw api_base/key) remain
  possible — that's the actual current CLI behavior — tucked under "custom endpoint".

### Sandboxes (`/sandboxes`)

**Real basis**: the `sandboxes` table (`name, kind ∈ opensandbox|local|ssh, image,
workdir`) with seed rows `git`, `python`, `local`; `create_sandbox_by_name` resolves
by name; `runs.sandbox_id` links runs. 🔶 thin backend — data model exists, needs
`GET/POST /api/sandboxes`.

- **List**: EntityList — name, kind Badge (`opensandbox`→blue, `local`→amber,
  `ssh`→muted), image-or-workdir column, run count. Note: sandboxes are *specs*, not
  live containers — a sandbox instance lives at most one Run (glossary). So no
  "running/stopped" status on this screen; liveness belongs to the run header.
- **Detail Drawer**: KeyValueList of the spec + recent runs that used it.
- **Create Drawer**: name + kind select; kind switches the one extra field —
  `opensandbox`→image, `local`→workdir, `ssh`→host/user (🔴 `ssh` kind is
  `NotImplementedError` in `infra/sandboxes.py` — the form shows it disabled with
  "not implemented in backend", honest over aspirational).
- The old SandboxScreen's ContainerPanel/Toolbelt (live container internals) is cut;
  if we later want "what's inside the sandbox of run X", that's a run-detail panel,
  not a management screen.

### Skills catalog (`/skills`)

🔴 **needs backend, entirely.** There is no skills concept anywhere in `core/` — no
table, no registry, no field on `build_agent`. Nearest real cousins:
**memory presets** (`core/memory/presets.py` — named, describable, per-run) and
**middleware** (`HistoryMiddleware` etc. — named behaviors attached to agents).

Design (so the backend has a target), deliberately minimal:

- **Catalog**: EntityList of skill cards — name, one-line description, "used by"
  agent-kind badges, source badge (`builtin`).
- **Detail**: Drawer — description, full instruction body in CodeBlock (markdown
  rendered as plain mono text v1 — no markdown renderer dependency), agents/nodes
  that reference it (links to `/runs/:id` inspector).
- **Read-only in v1.** No create/edit/assign UI until the backend semantics exist —
  designing an editor for an undefined concept is the over-engineering trap.

**Pragmatic recommendation**: ship `/skills` *last*, and propose the backend start
with a static registry (a dict, like `MEMORY_PRESETS`) served over one GET — that
also naturally serves memory presets on the same screen or as a section here, which
*are* real today and give the screen non-fictional content on day one.

---

## 4. Component breakdown

### Reuse as-is (no changes)

`Panel`, `PanelHeader`, `Badge`, `Button`, `TextInput`, `StatusDot`, `Meter`,
`Sparkline`, tone system (`toneVar`), `AppShell`/`TopBar`/`StatusBar` (rewire labels
only), `useAsync` + `resources.ts` hook pattern, `useRunStream` (reducer survives —
event types change, mechanics don't), `ActiveRunContext` (now keyed by route param),
mock-as-executable-spec discipline, `format.ts`.

### New reusable components (primitives unless noted)

| Component | One-line responsibility |
|---|---|
| `GraphCanvas` (feature: run) | Pannable SVG surface: renders nodes+edges, drag-to-reposition, single-select, emits `onSelect(nodeId)`. |
| `NodeInspector` (feature: run) | Tabbed right panel showing the selected node's spec + live data; degrades per-tab when spec data is absent. |
| `Tabs` | Terminal-style tab strip (chips + active underline), controlled `value/onChange`. |
| `CodeBlock` | Monospace scrollable `<pre>` with copy button; used for prompts, payloads, report JSON. |
| `KeyValueList` | Aligned label/value rows with optional per-row tone (promotes the pattern living in `SandboxInfo.rows`). |
| `EntityList` | Generic list-page table: typed columns, row click, empty state; backs runs/connections/sandboxes/skills lists. |
| `Drawer` | Right-side overlay panel for detail/create; one component, `title` + children, `Esc`/backdrop close. |
| `StatusBadge` (lib fn + Badge) | Maps `RunStatus`→tone/label in one place (replaces `severity.ts` as the tone-mapping module — `status.ts`). |

Eight new pieces total; four are trivial (`Tabs`, `CodeBlock`, `KeyValueList`,
`StatusBadge`).

### Explicitly NOT building (over-engineering flags)

- **No graph library** (react-flow/dagre/elkjs): 3 nodes, linear, ~150 lines of SVG
  + a rank-by-topo-sort layout. Revisit only when real sub-agent fan-out exists.
- **No zoom/minimap** on the canvas — pan covers a graph this size.
- **No separate Reports list screen** — it's a runs-list filter.
- **No Repositories screen** in v1 — a group-by facet on `/runs`.
- **No markdown renderer, no virtualization lib** — the stream already renders as
  capped-length plain rows; cap the DOM at last N rows + "load earlier" instead.
- **No skills editor/assignment UI** — read-only catalog until backend semantics exist.
- **No TanStack Query yet** — `useAsync` still covers seven screens of read-mostly data;
  the swap recipe in ARCHITECTURE.md remains the exit.

---

## 5. Contract additions (`src/api/contract.ts` style)

The biggest change is subtractive: delete `Finding`, `Severity`, `Confidence`,
`FindingCounts`, `CweStat`, `SevBar`, findings endpoints, and re-true `RunStatus`.

```ts
// ── statuses: adopt the backend machine verbatim (schemas.py) ──────────────
export type RunStatus = "pending" | "running" | "succeeded" | "failed" | "interrupted";
export const TERMINAL_STATUSES = ["succeeded", "failed", "interrupted"] as const;
// resume: failed|interrupted -> pending, only via resubmit (claim). succeeded absorbing.

// ── runs (mirrors the runs table + runtime) ────────────────────────────────
export interface Run {
  id: string;                    // runs.id
  repositoryId: string;
  repoUrl: string;               // repositories.url
  repo: string;                  // display slug, derived
  commitSha: string | null;
  status: RunStatus;
  error: string | null;          // runs.error
  stopReason: string | null;     // orphan_recovered | cancelled | shutting_down
  cancelRequestedAt: string | null; // lets UI show "cancelling…" honestly
  attempt: number;               // resume counter
  connection: { apiBase: string; model: string; keyMasked: string }; // llm_* columns
  sandbox: string | null;        // sandboxes.name via sandbox_id
  memoryPreset: string | null;   // 🔶 needs a column; real concept (presets.py)
  hasReport: boolean;            // report JSONB not null
  startedAt: string; finishedAt: string | null; updatedAt: string;
  metrics: { tokens: number; elapsedSec: number }; // 🔶 tokens need accounting
}

export interface SubmitRunRequest {
  repoUrl: string;
  connectionId?: string;         // 🔴 once connections table exists
  model?: string; apiBase?: string; apiKey?: string; // current per-run override path
  sandbox?: string;              // sandbox name (create_sandbox_by_name)
  memoryPreset?: string;
}
// POST /api/runs is idempotent per (repo, commit, model); surface the disposition:
export interface SubmitRunResponse {
  run: Run;
  disposition: "created" | "resumed" | "already_succeeded" | "attached"; // SubmitDisposition
}

// ── report (shape = nodes.py::report output, stored in runs.report) ────────
export interface Report {
  repoUrl: string;
  commit: string;
  description: string;                    // LLM 3-6 sentence summary
  structure: {
    fileCount: number; totalBytes: number; truncated: boolean;
    languages: Record<string, number>;    // ext -> count
    keyFiles: string[]; files: string[];
  };
  modules: { path: string; docstring: string | null; classes: string[]; functions: string[] }[];
  dependencies: string[];
  skippedFiles: string[];
  error?: string;                         // failed-run report variant
}
// GET /api/runs/:id/report — ✅ data exists, endpoint 🔶

// ── event stream (run_events + runtime stream) ─────────────────────────────
export type RunEventType =
  | "agent_start" | "model_message" | "tool_call" | "agent_finish"  // run_events.kind
  | "status" | "phase" | "log" | "gap";                             // stream-level
export interface RunEvent {
  cursor: number;               // run_events.id — monotonic, replayable
  ts: string;
  type: RunEventType;
  agent?: string;               // node id: "scan" | "parse" | "report" | future sub-agents
  message?: string;
  data?: unknown;               // typed per kind; model_message = message_to_dict shape
}
// GET /api/runs/:id/events?cursor= (SSE) — replay + live, `gap` when cursor
// fell out of the buffer (MemoryStreamBridge semantics, unchanged from today).

// ── graph + node specs ─────────────────────────────────────────────────────
export type NodeStatus = "queued" | "running" | "done" | "halted";
export interface GraphNode {
  id: string; label: string;
  kind: "procedural" | "agent";  // scan/report vs build_agent-based
  status: NodeStatus;            // derived from agent_start/finish events + run status
}
export type GraphEdge = { from: string; to: string; conditional?: boolean };
export interface RunGraph { runId: string; nodes: GraphNode[]; edges: GraphEdge[] }
// ✅ derivable: LangGraph compiled graph exposes nodes/edges (get_graph()).

export interface NodeSpec {                // 🔴 needs backend: a static registry
  id: string;
  description: string;
  systemPrompt: string | null;             // _DESCRIBE_PROMPT / build_agent system_prompt
  tools: { name: string; description: string }[];
  skills: string[];                        // 🔴 skill ids, once skills exist
}
// GET /api/graph/nodes (static per backend version, not per run)

// ── connections 🔴 (new table, mirrors sandboxes pattern) ──────────────────
export interface Connection {
  id: string; name: string; apiBase: string; model: string;
  keyMasked: string;             // raw key is write-only
  createdAt: string;
}
// GET/POST/DELETE /api/connections; POST /api/connections/:id/check → {ok, latencyMs, error?}

// ── sandboxes 🔶 (table exists; needs endpoints) ───────────────────────────
export interface SandboxSpec {
  id: string; name: string;
  kind: "opensandbox" | "local" | "ssh";   // ssh: table allows it, backend NotImplemented
  image: string | null; workdir: string | null;
  createdAt: string;
}
// GET/POST /api/sandboxes

// ── skills 🔴 (no backend concept; propose static registry first) ──────────
export interface Skill {
  id: string; name: string; description: string;
  body: string;                  // instruction text
  usedBy: string[];              // node/agent ids
}
// GET /api/skills

// ── memory presets ✅ concept (presets.py) / 🔶 endpoint ────────────────────
export interface MemoryPreset { name: string; description: string; production: boolean }
// GET /api/memory-presets — feeds the submit form + skills screen section
```

Per house rules, every addition lands in `contract.ts` + `client.ts` + **both**
adapters; the mock stays the executable spec (statuses walk `pending → running →
succeeded`, terminal sticky, resume produces `disposition: "resumed"`, cursor replay
+ gap behavior preserved).

---

## 6. Build sequencing

Each step ships independently and the app stays walkable against the mock throughout.

1. **Contract re-truing** (pure frontend, unblocks everything): new `RunStatus`,
   `Run`, `RunEvent`, `Report` types; rewrite `mock.ts`/`demo-data.ts` to the real
   status machine and `agent_start/model_message/tool_call/agent_finish` events;
   delete the findings/severity layer; add `status.ts` tone map. TopBar/StatusBar
   relabel (drop pause). *Biggest bang, zero new components.*
2. **Runs list + Report** (`/runs`, `/runs/:id/report`): `EntityList`, `KeyValueList`,
   `CodeBlock`, `StatusBadge`; runs list with status filters + succeeded-only
   "reports" filter; report screen renders `Report` (description panel, languages
   bars via `Meter`, modules table, dependencies). *Backend: `GET /api/runs`,
   `GET /api/runs/:id/report` — both read existing tables.*
3. **Run detail w/ interactive graph** (`/runs/:id`): `GraphCanvas` (pan/drag/select),
   `Tabs`, `NodeInspector` with the two ✅ tabs (overview, events), stream chips +
   hover coupling. Prompt/tools/skills tabs render their honest "unavailable" state.
   *Backend: SSE events endpoint over `run_events`.*
4. **Sandboxes** (`/sandboxes`): `Drawer` + reuse of EntityList/KeyValueList; ssh kind
   visible-but-disabled. *Backend: trivial GET/POST over the existing table.*
5. **Connections** (`/connections`) + LaunchModal connection select. *Backend: new
   table + CRUD + check endpoint — schedule the backend work here, not earlier.*
6. **NodeSpec tabs + Skills** (`/skills`, inspector prompt/tools/skills tabs):
   frontend is small by now (one screen reusing list/drawer, filling existing tabs);
   gated entirely on the backend registry. Memory presets section gives it real
   content on day one.
7. **Dashboard re-grounding** (last, optional): runs-by-status tiles, token spend
   sparkline, recent activity from run_events. Cut it from v1 scope if time-boxed —
   `/runs` already answers "what's happening".

### Risk / honesty summary

| Feature | Verdict |
|---|---|
| Runs list, run detail, event stream, report | ✅ renderable from existing tables/state |
| Graph nodes+edges, node status, per-node events | ✅ derivable (LangGraph graph + run_events) |
| Sandboxes mgmt | 🔶 table exists, endpoints don't; `ssh` kind not implemented |
| Tokens metric, memory-preset-per-run column | 🔶 small backend additions |
| Connections (named, saved) | 🔴 new table + CRUD |
| System prompt / tools per node | 🔴 needs a NodeSpec registry (small; `build_agent` params are the source) |
| Skills | 🔴 concept doesn't exist; ship read-only catalog against a static registry, editor never (yet) |
