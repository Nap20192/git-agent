# git-agent — real domain model (evidence-based)

Backend read at worktree root. All refs are repo-relative `file:line`.

## Big picture

git-agent is **not** a security scanner. It clones a git repo into a sandbox, walks the file tree, AST-parses Python modules, reads dependency manifests, asks one LLM call for a 3–6 sentence project description, and emits a JSON **Report** (`core/agents/nodes.py:188-211`). One linear LangGraph: `scan → parse → report` (`core/agents/graph.py:40-52`). Around it sits a durable run runtime ("a run is a resource, not a request", `core/runtime/runtime.py:1-7`).

Two execution paths today:
- **CLI** (`main.py:17-29`): builds graph directly, prints report JSON. No runs row, no runtime.
- **Runtime facade** (`core/runtime/runtime.py::Runtime`): submit/subscribe/events/cancel/wait — durable, idempotent, resumable. Wired **only in tests** (`tests/unit/test_runtime.py:335`, `tests/integration/test_run_store_pg.py`). **There is no HTTP API yet** — the docstring says "HTTP-слой позже мапит ConflictError→409, subscribe→SSE" (`core/runtime/runtime.py:5-7`). A frontend needs that HTTP layer built.

## Entities

### Run
Table `runs` (`migrations/001_init.sql:8-25` + `migrations/004_runtime.sql`):
`id, repository_id (FK), commit_sha, llm_api_base, llm_api_key, llm_model, status, error, report JSONB, started_at, finished_at, sandbox_id (FK, 003:15), stop_reason, cancel_requested_at, owner_worker_id, lease_expires_at, attempt (default 1), updated_at`.

- **Identity = idempotency key**: unique `(repository_id, commit_sha, llm_model)` (`migrations/004_runtime.sql:16`). Same triple ⇒ same run, always. Memory preset is **not** part of identity (no column; resolved from env/arg at agent-build time).
- **Statuses** (`core/runtime/schemas.py:11-20`): `pending | running | succeeded | failed | interrupted`. Active = {pending, running}; terminal = {succeeded, failed, interrupted}. Terminal statuses are never overwritten (CAS-guarded, `infra/run_store.py:1-7`).
- **Admission** `RunStore.claim` (`core/ports.py:54-75`): atomic INSERT / resume / takeover / ConflictError. succeeded ⇒ returned as-is (`already_succeeded`); failed/interrupted ⇒ CAS to pending, attempt+1, error/report cleared (`resumed`); active with valid lease ⇒ `ConflictError` (future HTTP 409); active with expired lease ⇒ takeover-resume.
- **Submit dispositions** (`schemas.py:53-58`): `created | resumed | already_succeeded | attached`.
- **Lease/heartbeat**: `owner_worker_id` + `lease_expires_at`, renewed via `renew_lease` which also returns `cancel_requested` (cancel mailbox) (`core/ports.py:83-91`). Lost renewal ⇒ `ownership_lost` fence: zero further durable writes, but `publish_end` always fires (`core/runtime/worker.py:119-139`).
- **Cancel** (`schemas.py:61-65`): outcomes `cancelled | requested | taken_over | not_cancellable | not_found`. Cross-process cancel = `cancel_requested_at` timestamp read at lease renewal.
- **Resume**: graph re-invoked with input `None` ⇒ LangGraph continues from PostgresSaver checkpoint under the same `thread_id = run_id` (`core/runtime/worker.py:89-90`).
- **Orphan recovery**: `claim_for_takeover` CAS active→failed with `stop_reason='orphan_recovered'`, error "Worker crashed or lease expired..." (`schemas.py:42-45`, `core/ports.py:111-114`).

### Run status machine (`core/runtime/schemas.py:25-39`)

| from \ to | pending | running | succeeded | failed | interrupted |
|---|---|---|---|---|---|
| pending | – | ✓ | – | ✓ | ✓ |
| running | – | – | ✓ | ✓ | ✓ |
| succeeded | – | – | – | – | – (absorbing) |
| failed | ✓ *claim only* | – | – | – | – |
| interrupted | ✓ *claim only* | – | – | – | – |

`failed/interrupted → pending` only via `claim` (resume = fresh admission, `assert_transition` `via_claim` guard, `schemas.py:35-39`). Formal model: `formal/RuntimeCore.lean`, checked in pytest (`tests/unit/test_formal.py`).

### Repository
`repositories`: `id, url (unique), name, created_at` (`migrations/001_init.sql:1-6`). Created lazily via `get_or_create_repository` callback (`core/runtime/runtime.py:33,62`).

### Report
JSONB on the run, produced by the `report` node (`core/agents/nodes.py:188-211`):
`repo_url, commit, description` (LLM-written prose), `structure {file_count, total_bytes, truncated, languages (ext→count), key_files, files[]}`, `modules[] {path, docstring, classes[], functions[]}` (Python AST only, max 40 files ≤80KB each, `nodes.py:45-47`), `dependencies[]` (pyproject/requirements, `nodes.py:117-131`), `skipped_files[]`. Error case: just `{repo_url, error}`.

### Graph / Nodes
Fixed linear pipeline, not user-configurable (`core/agents/graph.py:40-52`): `START → scan → (parse | report on error) → report → END`. Each node's errors go to `state["error"]` and short-circuit to report (`graph.py:23-37`). State = `RepoState` TypedDict: `repo_url, scan, parse, report, error` (`core/agents/state.py:4-9`).
- **scan** (`nodes.py:55-95`): `git clone --depth 1`, `rev-parse HEAD`, `find`+`stat` listing, skips `.git/__pycache__/node_modules/...`, caps at 5000 files.
- **parse** (`nodes.py:144-185`): AST-parses Python files, reads deps, **one** `model.ainvoke(prompt)` with hardcoded Russian describe-prompt `_DESCRIBE_PROMPT` (`nodes.py:134-141`).
- **report** (`nodes.py:188-211`): assembles the JSON above.

### Sandbox
Port `core/ports.py:24-45`: `repo_dir`, `run(command, timeout_seconds) → stdout`, `close()`. Contract: git/find/stat/cat available inside.
Table `sandboxes` (`migrations/003_sandboxes.sql`): `id, name (unique), kind ∈ {opensandbox, local, ssh}, image (opensandbox), workdir (local), created_at`. Seeded rows: `git` (alpine/git), `python` (python:3.12-slim), `local`. **Many sandboxes: yes** — created by name from the table (`infra/sandboxes.py:23-31`); `ssh` kind is a CHECK value with **no implementation** (`NotImplementedError`, `sandboxes.py:30-31`). Adapters: `infra/opensandbox.py::OpenSandboxAdapter` (OpenSandbox service, port 8090), `infra/localsandbox.py::LocalSandbox` (host exec, explicitly NO isolation). Run picks one via `sandbox_name` (`runtime.py:58`, `main.py --sandbox`); `runs.sandbox_id` FK exists but the runtime path passes name, not id.

### Connection (LLM)
No dedicated table/entity. A "connection" = the triple `llm_api_base, llm_api_key, llm_model` stored **per run row** (`migrations/001_init.sql:13-15`), entered per run (CLI flags or `LLM_*` env defaults, `core/agents/llm.py:9-23`, `core/config.py:22-24`). Any OpenAI-compatible endpoint (`init_chat_model(..., model_provider="openai")`). **Many different connections: yes**, trivially — each run carries its own; but there is no saved-connections registry (net-new if the UI wants named reusable connections). Note: `llm_api_key` is stored **plaintext** in the runs table and returned by `RunStore.get` — the HTTP layer must redact it.

### RunEvent / streaming
Table `run_events`: `id (cursor), run_id, kind, payload JSONB, created_at` (`migrations/002_run_events.sql`); cursor index `(run_id, id)` (`004:20`).
Two producers, two vocabularies:
1. **Worker path (the live one)**: each `graph.astream(stream_mode=["updates","custom"])` chunk is serialized (`core/runtime/serialization.py`) and both published to the bridge and persisted with `kind = "updates" | "custom"` (+ ad-hoc `"error"` publish) (`core/runtime/worker.py:92-103,116`). So the real stream content = LangGraph node-update dicts (`{"scan": {...}}`, `{"parse": {...}}`, ...).
2. **HistoryMiddleware path** (`core/agents/middleware/history.py`): kinds `agent_start | model_message | tool_call | agent_finish` (002:4) — but this middleware is **not instantiated anywhere** in the run path (only defined + exported; grep shows no usage). It belongs to the `build_agent` world, not the graph.

Live stream: `MemoryStreamBridge` (`core/runtime/bridge.py:58-202`) — in-process, per-run journal, maxsize 512, ids `"{ms}-{seq}"`, O(1) cursor replay, heartbeat sentinel every 15s, `END_SENTINEL` on finish, honest `StreamGap{requested, earliest, latest}` when the cursor fell out of the buffer ⇒ client refetches durable history via `Runtime.events(after_id)` (`runtime.py:109-110`). Not Redis/SSE yet — memory-only, single process.

### MemoryPreset
`core/memory/presets.py::MEMORY_PRESETS` — ~20 named `MemoryConfig` frozen dataclasses (`core/memory/config.py`): `full_history`, `prod`, `prod_v2` (production, long-context providers only), `aggressive`, `sliding_window`, many `exp_*` experiment arms. Resolution: explicit arg > `GIT_AGENT_MEMORY_PRESET` env > production default per provider (`core/memory/__init__.py:90-95`, allowlist `presets.py:208-217`). **BUT**: presets feed `assemble_from_features` → `build_agent` (`core/agents/features.py:62-114`) — which the scan/parse/report graph never uses. So today presets affect nothing at runtime; they're plumbing for the future agent. Not stored on the run row.

### Agent / Tools / Skills / Sub-agents — the honest answer
- **`build_agent`** (`core/agents/factory.py:13-57`) wraps LangChain's `create_agent` with `model, tools, system_prompt, middleware/features, checkpointer`. **Never called in production code** — grep for `build_agent` hits only its definition and CLAUDE.md. The actual run uses the plain StateGraph.
- **Tools**: zero. No `BaseTool` is defined or passed anywhere; `tools` is a parameter with no callers. The graph nodes shell into the sandbox directly — those are not LangChain tools.
- **System prompt**: no system prompt exists. The only prompt in the run path is the inline `_DESCRIBE_PROMPT` template in `nodes.py:134-141`. `build_agent(system_prompt=...)` is an unused parameter. Memory presets carry `summary_prompt`s (`core/memory/prompts.py`) — summarization prompts, not agent system prompts, and also unused.
- **Sub-agents**: none. `RuntimeFeatures.subagent` is a feature flag defaulting to `False`, and `=True` raises "no built-in middleware yet" (`features.py:42,102-110`). No spawning code exists.
- **Skills**: the concept does not exist anywhere in the backend. Zero hits outside `.claude/` tooling files.

A "sub-agent inspector showing system_prompt + tools + skills" describes a backend that does not exist yet. What exists to inspect: the fixed 3-node graph, the sandbox commands it runs, one describe-prompt, the event stream, and the report.

## EXISTS vs NET-NEW (per frontend want)

| Frontend wants | Status | Evidence |
|---|---|---|
| Many runs, list + status lifecycle | **EXISTS** (data+runtime), **NET-NEW**: HTTP API + a `list_runs` query (store has only `get`/`list_expired`) | `runs` table, `Runtime`, `core/ports.py:77,117` |
| Live run view (streaming events) | **PARTIAL**: in-process bridge with cursor replay + gap contract; no SSE/WS endpoint, memory-only buffer | `core/runtime/bridge.py`, `runtime.py:92-107` |
| Run history / replay after finish | **EXISTS**: durable `run_events` + `events(after_id)` cursor pagination | `002_run_events.sql`, `runtime.py:109` |
| Reports | **EXISTS**: `runs.report` JSONB with the exact shape above — but it's repo-structure description, **not** vulnerabilities/CWE/exploits. The whole SAST framing is fantasy | `nodes.py:188-211` |
| Many connections | **PARTIAL**: per-run `llm_api_base/key/model` columns, any OpenAI-compatible endpoint; **NET-NEW**: saved/named connection registry, key redaction | `001_init.sql:13-15`, `llm.py` |
| Many sandboxes | **EXISTS**: `sandboxes` table, 3 seeded, pick per run by name; `ssh` kind declared but unimplemented; **NET-NEW**: CRUD API | `003_sandboxes.sql`, `infra/sandboxes.py` |
| Interactive agent graph | **PARTIAL**: the graph is real but static — always scan→parse→report; node progress derivable from `updates` events (`{"scan": ...}` keys). No dynamic topology | `graph.py:40-52`, `worker.py:92-99` |
| Sub-agent inspector (system_prompt, tools) | **NOT AT ALL**: no sub-agents, no tools, no system prompt in the run path; `build_agent` scaffolding exists unused | `factory.py`, `features.py:42,107` |
| Skills list | **NOT AT ALL**: concept absent from the backend | repo-wide grep |
| Cancel / resume / retry a run | **EXISTS** (runtime level): cancel mailbox, resume-from-checkpoint via resubmit, attempt counter | `runtime.py:125`, `ports.py:54-75`, `004:7` |
| Memory preset picker | **PARTIAL**: named presets + resolver exist; wired to nothing the run executes; not persisted per run | `core/memory/presets.py`, `features.py:69` |
| Any HTTP API at all | **NOT AT ALL**: only CLI + library facade; SSE/409 mapping is an explicit TODO in the docstring | `main.py`, `runtime.py:5-7` |
