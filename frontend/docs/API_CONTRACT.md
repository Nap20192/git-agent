# git-agent API Contract

Implementer-facing spec for the REST + SSE surface between this frontend and the git-agent
backend. `docs/openapi.yaml` is the **machine-readable source of truth** for the wire; the
TypeScript types in `src/api/contract.ts` mirror it for the client; this document is the narrative
half (endpoints, SSE framing, status machine, backend mapping). Keep all three in sync.

> **Honesty note.** There is **no HTTP backend yet** — git-agent is a CLI + library facade
> (`Runtime`) over a real durable runtime. The default adapter is the in-memory mock, which *is* the
> executable spec. `http.ts` is the shape the future FastAPI layer (a thin HTTP tier over the
> `Runtime` facade + the sub-agent system) must implement. The **HTTP layer and the named-connection
> registry are net-new**; the **sub-agent system, its statuses, token usage and tool receipts are
> REAL on master (68a7c56)** — `core/agents/subagents/`. Each row in the mapping table below is
> tagged. Direction: `docs/WAYFINDER.md`.

## Adapter selection

The UI depends only on the `GitAgentApi` interface (`src/api/client.ts`). Two adapters implement it:

| Adapter | File | Selected by |
|---|---|---|
| Mock (in-memory demo runs) | `src/api/mock.ts` (+ `demo-data.ts`) | `VITE_API` unset or ≠ `http` (default) |
| HTTP + SSE (real backend) | `src/api/http.ts` | `VITE_API=http` |

Selection happens once in `src/api/index.ts::createApi()`; components get the adapter via
`useApi()` / `ApiProvider` and never import a concrete one.

All HTTP paths are rooted at `BASE = "/api"`. In dev, Vite proxies `/api` to `http://localhost:8080`
(`vite.config.ts`, `server.proxy`). Requests/responses are JSON except the event stream, which is
`text/event-stream`.

## REST endpoints

Paths and shapes below are exactly what `src/api/http.ts` calls; all types are exported from
`src/api/contract.ts`. List endpoints wrap their array in an object so they can grow pagination
fields without a breaking change.

| `GitAgentApi` method | HTTP | Path | Request body | Response body |
|---|---|---|---|---|
| `listRuns()` | GET | `/api/runs` | — | `RunListResponse` (`{ runs: Run[] }`) |
| `getRun(id)` | GET | `/api/runs/:id` | — | `Run` |
| `submitRun(req)` | POST | `/api/runs` | `SubmitRunRequest` | `SubmitRunResponse` |
| `cancelRun(id)` | POST | `/api/runs/:id/cancel` | — | `Run` |
| `resumeRun(id)` | POST | `/api/runs/:id/resume` | — | `SubmitRunResponse` |
| `getReport(runId)` | GET | `/api/runs/:runId/report` | — | `Report` |
| `getGraph(runId)` | GET | `/api/runs/:runId/graph` | — | `RunGraph` |
| `getNodeSpec(runId, nodeId)` | GET | `/api/runs/:runId/nodes/:nodeId` | — | `NodeSpec` |
| `streamRunEvents(runId, opts)` | GET (SSE) | `/api/runs/:runId/events[?cursor=N]` | — | stream of `RunEvent` |
| `listConnections()` | GET | `/api/connections` | — | `{ connections: Connection[] }` |
| `createConnection(input)` | POST | `/api/connections` | `{ name, apiBase, apiKey, model }` | `Connection` |
| `deleteConnection(id)` | DELETE | `/api/connections/:id` | — | `204` |
| `checkConnection(id)` | POST | `/api/connections/:id/check` | — | `Connection` (with `lastCheck`) |
| `listSandboxes()` | GET | `/api/sandboxes` | — | `{ sandboxes: SandboxSpec[] }` |
| `createSandbox(input)` | POST | `/api/sandboxes` | `{ name, kind, image?, workdir? }` | `SandboxSpec` |
| `listCapabilities()` | GET | `/api/capabilities` | — | `{ capabilities: Capability[] }` |
| `listMemoryPresets()` | GET | `/api/memory-presets` | — | `{ presets: MemoryPreset[] }` |

Notes:

- `cancelRun` returns the run *after* the request is registered. Cancel is a request (mailbox — see
  below): the response may still be `running` with `cancelRequestedAt` set; the authoritative
  transition arrives as a `status` event on the stream.
- The raw API key on `createConnection` is write-only. Only `keyMasked` ever crosses the wire
  (`Connection.keyMasked`, `RunConnection.keyMasked`).

### Submit and its disposition

`submitRun` is **idempotent per `(repo, commit, model)`** — the backend reports what happened via
`SubmitResponse.disposition`:

| `SubmitDisposition` | Meaning |
|---|---|
| `created` | A new run row was claimed. |
| `resumed` | An existing failed/interrupted run was resumed from its checkpoint (attempt++). |
| `already_succeeded` | The triple already has a succeeded run; nothing to do. |
| `attached` | A matching run is already in flight; the caller is attached to it. |

Frontend consequence: `submitRun`/`resumeRun` may return a `Run` whose `id`, `createdAt`, and
progress predate the click. `resumeRun(id)` maps onto the same claim path with the run's own triple.

## Run status machine

```ts
export type RunStatus = "pending" | "running" | "succeeded" | "failed" | "interrupted";
export const TERMINAL_STATUSES = ["succeeded", "failed", "interrupted"];  // absorbing
export const ACTIVE_STATUSES   = ["pending", "running"];
```

Mirrors the backend runtime's `LEGAL_TRANSITIONS` + `assert_transition`
(`core/runtime/schemas.py`), whose invariants are formally modeled in `formal/RuntimeCore.lean`.
`contract.ts` exposes `isTerminal`, `isActive`, and `isResumable` (true only for `failed` /
`interrupted`) as the executable version.

| From | To |
|---|---|
| `pending` | `running`, `failed`, `interrupted` |
| `running` | `succeeded`, `failed`, `interrupted` |
| `succeeded` | — (terminal, sticky) |
| `failed` | `pending` (resume via claim) |
| `interrupted` | `pending` (resume via claim) |

- **Terminal-sticky.** Once a run reaches a terminal status it never spontaneously leaves it; the
  mock enforces this (`LivePipelineRun.cancel` no-ops `if (isTerminal(...))`). The only way out of
  `failed`/`interrupted` is an explicit resume, which claims the row back to `pending`.
- **No pause.** There is no `paused`/`cancelling` state. A cancel is signalled by
  `cancelRequestedAt` on a still-`running` run (UI shows a "cancelling…" chip) and lands as
  `interrupted` with `stopReason: "cancelled"`.
- **Admission / claim.** `POST /api/runs` maps to `Runtime.submit()`, an atomic CAS claim on the
  `runs` row unique on `(repository_id, commit_sha, llm_model)`. `StopReason` is
  `orphan_recovered | cancelled | shutting_down | null`.

## Sub-agents

Real on master (`core/agents/subagents/`). The topology is a **strict star of depth 1**: a *lead*
delegates self-contained tasks via the `task` tool to *sub-agents*; sub-agents structurally do **not**
have the `task` tool and cannot delegate further. There is currently **one registry type**,
`general-purpose` (`registry.py::GENERAL_PURPOSE`), which inherits the lead's model and gets exactly
the sandbox toolset (`tools.py`: `sandbox_run`, `read_file`) — no per-type tools/skills.

The `task` tool inputs (`task_tool.py`): `description` (3-5 word progress label), `prompt` (the full,
self-contained assignment — the sub-agent sees nothing else), `subagent_type`, and optional
`acceptance_criteria: string[]`. One invocation = one `TaskDelegation`.

### Sub-agent status machine

`SubagentStatus` (`contract.py`) is a closed enum: **`pending | running`** (active) →
**`completed | failed | cancelled | timed_out`** (terminal, first-writer-wins). Terminalisation is
owned split: the executor writes `completed`/`failed`; the `task` tool writes `timed_out` (on
`TimeoutError`) and `cancelled` (on `CancelledError`, then re-raises).

A cap is an **additive** field `stopReason: "token_capped" | "turn_capped" | "loop_capped"` (or
`null`), **never a new status** — capped-with-output is `completed`, capped-without is `failed`. Old
consumers ignore an unknown optional field; a new enum value would break them.

### Delegation shape

`TaskDelegation` (leaf of the star) carries the `task` inputs plus the terminal metadata
(`StructuredSubagentResult`): `status`, `stopReason`, `error`, `acceptanceCriteria`, `tokenUsage`,
`resultBrief`, `toolReceipts`, `receiptVerdict`, `startedAt`, `completedAt`.

- **`TokenUsage`** `{ inputTokens, outputTokens, totalTokens }` — real, summed across the sub-agent's
  steps (`task_tool.py::_cumulative_usage`); replace-semantics on the wire (do **not** re-sum with
  progress frames). `RunMetrics.tokenUsage` is the run-level cumulative sum.
- **`ToolReceipt`** `{ id, tool, summary }` — a tool-call receipt the sub-agent must cite in its
  report (`receipts.py`).
- **`ReceiptVerdict`** `{ cited, uncited, ok }` — citation verification of the report against its
  receipts; only computed for a `completed` delegation with a non-null receipt ledger.

On the graph, a delegated sub-agent is a `GraphNode` with `kind: "agent"`, `parentId` = the lead id,
and the runtime fields `subagentType`, `description`, `tokenUsage`, `stopReason`, `subStatus`. Its
`NodeSpec` carries the registry type (`subagentType`, `maxTurns`, `timeoutSeconds`) and the live
`delegation`.

## Event stream

`GET /api/runs/:id/events` is Server-Sent Events. Each SSE `data:` line is one JSON `RunEvent`; the
HTTP adapter consumes them via `EventSource.onmessage` (default event name — the discriminator is the
`type` field inside the JSON).

```ts
export interface RunEvent {
  cursor: number;           // run_events.id — monotonic per-run, replayable via ?cursor=
  ts: string;               // ISO-8601
  type: RunEventType;
  agent?: string;           // node id ("scan"/"parse"/"report") or a sub-agent task_id
  level?: "info" | "warn" | "error";
  message?: string;
  data?: RunEventData;      // typed payload
}
```

### Event vocabulary (`RunEventType`)

Two producers feed one ordered, cursor-numbered stream (`worker.py` publishes every `(mode, chunk)`
from `graph.astream` through `MemoryStreamBridge` and persists it to `run_events`):

| Type | Producer | Meaning |
|---|---|---|
| `node_update` | LangGraph `updates` chunk (worker.py) | a pipeline node produced output |
| `custom` | LangGraph `custom` chunk (worker.py) | other custom stream chunk |
| `task_started` | `task` tool stream writer (task_tool.py) | a delegation began |
| `task_running` | `task` tool stream writer (task_tool.py, `on_step` from steps.py frames) | sub-agent progress step |
| `task_completed` / `task_failed` / `task_cancelled` / `task_timed_out` | `task` tool stream writer (task_tool.py `_terminal_event`) | delegation reached that terminal status |
| `status` | worker | run status changed (`data.kind: "status"`) |
| `log` | worker | human-readable log line |
| `gap` | stream bridge | `StreamGap` — cursor fell out of the replay buffer |

`RunEventData` is discriminated by `kind`:
- `node_status` `{ node, status }` and `status` `{ status: RunStatus }`;
- `task_started` `{ taskId, subagentType, description }`;
- `task_step` `{ taskId, messageIndex, frameKind: "ai"|"tool", text, toolName?, toolCalls? }` — the
  payload of a `task_running` event;
- `task_terminal` `{ taskId, subagentType, status, stopReason, error, usage }` — the payload of a
  `task_<terminal>` event; `usage` is the cumulative `TokenUsage` (replace-semantics).

The stream reducer (`src/hooks/useRunStream.ts`) folds these into per-node status + event buckets;
it drives the graph animation, so the client does not separately poll `getGraph` for status.

### Replay by cursor

- `?cursor=N` resumes **exclusively** after cursor `N`: the backend replays every buffered event with
  `cursor > N`, then continues live. Omit the param to start from the head. The mock's
  `LivePipelineRun.subscribe` implements exactly this and is the executable spec.
- Cursors are per-run, strictly increasing, assigned by the backend (`MemoryStreamBridge`). Clients
  track the highest cursor seen and pass it on reconnect; replay from a still-buffered cursor is O(1).
- If the requested cursor has fallen out of the buffer, the backend emits a **`gap` event** first
  (mirroring the runtime's `StreamGap`), then continues from the oldest buffered event. On `gap`, the
  client must re-fetch snapshot state (`getRun`, `getGraph`) and treat the stream as resumed-with-loss.
- Stream errors surface through `StreamOptions.onError`; the returned `Unsubscribe` closes the
  `EventSource`.

## Contract → backend mapping

Machine-readable per-schema mapping: `docs/openapi.yaml`. "real" = exists on master today; "net-new"
= the future HTTP tier / a table that does not exist yet.

| Contract type | Backend concept | Status |
|---|---|---|
| `Run` | Row in the `runs` table (commit_sha + per-run `llm_api_base/key/model` columns) | real |
| `RunStatus` / `TERMINAL_STATUSES` | `LEGAL_TRANSITIONS` status machine (`core/runtime/schemas.py`) | real |
| `SubmitDisposition` / idempotency | `Runtime.submit()` claim CAS, unique `(repository_id, commit_sha, llm_model)` | real |
| `RunEvent` + `cursor` | `run_events` table / `MemoryStreamBridge` replay-by-cursor (`worker.py` publishes) | real |
| `gap` event | `StreamGap` (cursor fell out of the replay buffer) | real |
| `Report` / `ReportStructure` / `ReportModule` | `core/agents/nodes.py::report` output stored in `runs.report` | real |
| `RunConnection` | per-run `llm_*` columns on the `runs` row | real |
| `SandboxSpec` | `sandboxes` table (kind opensandbox/local/ssh) | real |
| `MemoryPreset` | named `MemoryConfig` in `core/memory/presets.py` | real |
| Cancel endpoint | `cancel_requested_at` mailbox, read on lease renewal | real |
| `SubagentStatus` / `SubagentStopReason` | `core/agents/subagents/contract.py` (closed enum + additive cap) | real |
| `TaskDelegation` / `task_*` events | `subagents/task_tool.py` — the `task` tool + its stream writer | real |
| `SubagentType` | `subagents/registry.py::SubagentConfig` (one type: `general-purpose`) | real |
| `TokenUsage` (delegation + `RunMetrics.tokenUsage`) | `contract.py::normalize_token_usage` + `task_tool.py::_cumulative_usage` | real |
| `ToolReceipt` / `ReceiptVerdict` | `subagents/receipts.py` (cited handles + citation verdict) | real |
| sub-agent `GraphNode` fields / `NodeSpec.delegation` | lead+sub-agent star projected from `task_*` stream | real (projection) |
| `NodeSpec.tools` (sub-agent) | fixed sandbox toolset `subagents/tools.py` (`sandbox_run`, `read_file`) | real |
| `Capability` (`source: subagent`) | a registry sub-agent type (`registry.py`) | real |
| `Capability` (`source: tool`) | a sandbox tool (`tools.py`) | real |
| `Capability` (`source: capability` / `memory_preset`) | `RuntimeFeatures` flags / memory presets, labelled `active` | real (labelled) |
| All `/api/*` HTTP routes + SSE framing | thin FastAPI tier over the `Runtime` facade | **net-new** |
| `Connection` (named registry) | per-run today; a saved-connection table | **net-new** |

## Errors

Non-2xx responses carry the normalised `ApiError` body:

```ts
export interface ApiError { error: { code: string; message: string } }
```

The HTTP adapter (`http.ts::req`) surfaces errors as `Error("<status> <error.message>")`, falling
back to the HTTP status text when the body isn't JSON. `204` returns `undefined`. SSE failures arrive
via `onError`; the client reconnects with its last cursor.
