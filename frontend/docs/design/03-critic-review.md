# Critic pass — pressure test of OUT-domain.md + OUT-ux.md

Verdict up front: the domain doc is solid and I found no fabrications in it. The UX doc
is 80% right and admirably subtractive, but it has **one factual error that poisons the
contract** (§4.1 below), keeps two speculative interactions the user asked for but a
3-node graph can't justify, and its "degraded tabs" answer to the skills problem ships
a UI of apologies. Fixes below.

---

## 1. The central tension: sub-agent inspector + skills vs. a backend that has neither

**The UX doc's answer — grey out 3 of 5 inspector tabs ("unavailable for this backend")
and a read-only skills catalog against a future static registry — is the wrong call.**
The inspector is the marquee feature the user asked for. Shipping it with prompt/tools/
skills all rendering "unavailable" means the centerpiece demos as a stub. A screen that
mostly apologizes teaches the user the product is fake — the exact thing we're trying
to stop doing.

The honest reframe: the user's underlying want is *"click a node, see fully what it
does."* For today's procedural nodes that is **100% satisfiable with real data**:

- `scan` = `git clone --depth 1`, `rev-parse HEAD`, `find`+`stat`, skip rules, 5000-file cap
- `parse` = Python AST walk, dependency manifests, **one** LLM call with `_DESCRIBE_PROMPT` (a real prompt, showable verbatim)
- `report` = JSON assembly, exact output schema

A backend `NodeSpec` registry is a ~50-line static dict. That is *cheaper than building
the degraded-state UI* and makes the inspector real on day one. So: **don't ship
unavailable tabs — ship a smaller, fully-true tab set**: `overview | spec | events`,
where **spec** merges prompt + operations (for `parse` it shows the actual
`_DESCRIBE_PROMPT`; for `scan`/`report` it shows the sandbox commands — which is
exactly the "tools" info the user wants, under its true name). When `build_agent`
nodes exist, the same tab renders `system_prompt` + `tools` with zero redesign.

**Skills.** The concept has zero backend hits; inventing a `/skills` route around it —
even read-only — creates a fictional noun the backend must then grow into. The true
"capabilities" of this system are:

- **Memory presets** (`core/memory/presets.py`) — ~20 named, described, real objects
- **RuntimeFeatures** (`core/agents/features.py`) — 8 real flags: sandbox/memory/subagent/vision/auto_title/guardrail/loop_detection/token_budget

**Recommendation: reframe "skills" → "capabilities", and do NOT give it a v1 screen.**
Two reasons the UX doc's own fallback ("serve memory presets on the skills screen")
under-sells: (a) it keeps the fictional name; (b) — critically — **presets are wired to
nothing the run executes today** (domain doc §MemoryPreset), and `RuntimeFeatures=True`
literally raises "no built-in middleware yet". A capabilities catalog would be a screen
of real names with zero runtime effect — technically honest, practically misleading
unless every row is stamped "not active in run path", at which point it's a museum.
Put memory presets where they'll become honest first: a picker in the submit form +
a field on the run header (needs the small per-run column). Add a `/capabilities`
screen only when at least one feature flag has a wired middleware. Tell the user
plainly: *skills don't exist in your backend; the inspector is designed so that when
you build sub-agents on `build_agent`, prompt/tools render without redesign.*

## 2. Over-engineering (the ladder, applied)

The UX doc already cut the right big things (graph lib, zoom, reports screen, repos
screen, markdown renderer, TanStack). Remaining fat:

- **Pan + drag-to-reposition + localStorage layout persistence: cut from v1.** The
  graph is 3 nodes, fixed, forever fitting in the panel — pan moves nothing anywhere
  useful, and drag persistence keyed "by the graph's node-id set" is infrastructure
  for a topology that cannot change. The user asked for pan/drag, so this is their
  call (Decision D2), but my recommendation is: static auto-layout + **click-to-select
  + live status tones + per-node event badges** — that's where all the perceived
  interactivity actually lives. Selection/hover is ~60 lines; pan/drag machinery with
  pointer capture and persistence roughly triples the canvas code to animate nothing.
- **`EntityList` (generic typed-column table): premature.** With v1 scoped to runs +
  run detail + report (§5), it has exactly one consumer. Build the runs table
  concretely; extract the generic when connections/sandboxes actually land.
- **`Drawer`: defer** — its consumers (connections/sandboxes/skills detail) are all
  out of v1.
- **Hover coupling both directions** (event row hover → node outline): polish, defer.
  Keep node-select → row highlight only.
- **`tokens` metric in run header and dashboard: cut.** No token accounting exists
  anywhere in the backend; this is the one fantasy number left in the contract.
- **Dashboard (`/dash`): cut from v1 entirely.** The doc already half-admits this.

Component count drops from 8 to 5: `Tabs`, `CodeBlock`, `KeyValueList`, `StatusBadge`,
`GraphView` (static) + `NodeInspector`. That's the first shippable slice.

## 3. Sequencing & the missing HTTP API

"Keep building against the mock, backend later" is **only** sound if the mock speaks
the real backend's dialect. Today the proposed contract has landmines the real backend
can't cheaply serve:

1. **The event vocabulary is wrong — this is the big one, see §4.** Fix before writing
   another line of mock.
2. **SSE over `MemoryStreamBridge` forces a topology decision.** The bridge is
   in-process, single-buffer. Live tail works only if the HTTP server and the run
   worker share a process. That's fine for v1 — but it must be *decided*: the FastAPI
   app embeds `Runtime` (one process, one worker). The saving grace already exists:
   `StreamGap` → refetch via `Runtime.events(after_id)` means a restarted/second
   server degrades to durable replay, not silence. Pin this in the contract notes.
3. **`RunStore` has no `list_runs`** — the home screen's one query doesn't exist yet.
   Small, but it means even the runs list is "backend work", so the "backend later"
   framing is already false for screen #1.
4. **Key redaction is a hard gate, not a nicety**: `llm_api_key` is plaintext in the
   runs table and returned by `RunStore.get`. The first `GET /api/runs` written
   naively leaks every key. `keyMasked` in the contract is right; flag it as a
   security requirement on the HTTP layer, not a display choice.
5. **Idempotency will surprise the UI.** Submit is keyed `(repo, commit, model)` — the
   "new run" button can legally return someone else's in-flight run (`attached`) or a
   finished one (`already_succeeded`). The contract's `disposition` field is the right
   answer, but the UX doc never designs the moment: LaunchModal must handle "you asked
   for a run and got an existing one" as a first-class outcome, not an edge case.
   Also **verify how `commit_sha` is known at admission** (submit happens before
   clone) — if it's resolved via `ls-remote` server-side, submits have network
   latency; if it's backfilled, the uniqueness story needs explaining. Neither doc
   answers this.
6. **Per-node system prompts / NodeSpec**: cheap (static dict), *as long as it stays
   per-backend-version, not per-run* — the contract got this right (`GET
   /api/graph/nodes`). Don't let it drift to per-run.

**Recommendation:** build the thin HTTP layer in v1, not "later" — it's FastAPI + ~6
routes over an already-finished facade (`submit/get/events/subscribe/cancel` + new
`list_runs`), and the runtime docstring literally pre-plans the mapping
(ConflictError→409, subscribe→SSE). The mock stays as the executable spec and test
double, but the contract gets validated against a real server within v1, which is the
only thing that stops mock-drift.

## 4. Fidelity check — what's still fantasy in the UX doc

1. **The `RunEventType` vocabulary is built on unwired code (factual error).**
   The doc marks the inspector events tab ✅ because "`run_events.kind` ∈ agent_start /
   model_message / tool_call / agent_finish, all carry the agent" and asserts
   "HistoryMiddleware is per-agent already". Verified: `HistoryMiddleware` is defined
   and exported but **instantiated nowhere in the run path**. The real stream —
   worker's `graph.astream(stream_mode=["updates","custom"])` — emits serialized
   LangGraph chunks with kinds `updates` / `custom` (+ ad-hoc `error`). The good news:
   node attribution is still derivable (update chunks are keyed by node name,
   `{"scan": {...}}`), so per-node filtering, status derivation, and event badges all
   survive — but the contract's event types, the mock generator, and every row
   renderer must be re-derived from `core/runtime/serialization.py` output. As
   written, step 1 "contract re-truing" would re-true the contract *into a different
   fiction*. Highest-priority fix.
2. **`NodeStatus = queued|running|done|halted`** quietly invents a second status
   vocabulary right after the doc's (correct) crusade against invented run statuses.
   Derive node state from real update-event presence + run status; name the states
   after what's observable (`pending|running|completed|error`), and note "queued"→
   derived tone in the doc, not the contract.
3. **`tokens` metric** — fantasy, no accounting anywhere (see §2).
4. **Under-used real concepts** (free wins the UX doc leaves on the table):
   - **`attempt` + `stop_reason`** are in the Run type but never given a surface. An
     "attempt N — previous attempt: orphan_recovered / cancelled" line in the run
     header is zero-cost honesty and shows off the runtime's best property
     (durability) — currently the product's most differentiated real feature and the
     UI barely mentions it.
   - **Memory-preset-not-in-identity is a UX trap the doc walks into**: LaunchModal
     offers a `memoryPreset` picker, but two submits with the same
     `(repo, commit, model)` and *different presets* are the **same run** — the second
     just attaches. If the picker ships, the collision needs a warning, or preset
     joins the identity key (backend decision). The doc offers the picker without
     noticing.
   - **CLI-vs-runtime dual path**: CLI runs (`main.py`) create no rows — they will
     never appear in the UI. Worth one line in the product docs so nobody files "my
     run is missing" as a bug.
5. Minor: §2 references "`GraphSpec`" but the contract defines `NodeSpec` — naming
   drift; the sandboxes screen correctly handles `ssh`-as-disabled (good); the
   Report/Run 1:1 collapse and the status-machine adoption are exactly right and
   should be defended against future scope creep.

## 5. Decisions for the user

| # | Decision | My recommendation |
|---|---|---|
| D1 | **Skills**: keep a "skills" catalog (fictional noun, backend must grow into it) vs. reframe as capabilities and defer the screen | **Reframe → capabilities; no `/skills` route in v1.** Presets go in the submit form + run header; inspector "spec" tab shows real prompts/commands under true names. Capabilities screen only when a feature flag is actually wired. |
| D2 | **Graph interactivity**: pan/drag/localStorage now (as you asked) vs. static layout + select/live-status only | **Static + select for v1.** On 3 fixed nodes pan/drag animates nothing; selection + live tones + event badges are where the interactivity you want actually lives. Pan/drag lands with the first dynamic topology. |
| D3 | **Backend**: thin FastAPI now vs. mock-only-until-later | **Build it in v1** — ~6 routes over a finished facade; the mock alone will drift (it already did, on the event vocabulary). Requires deciding: API server embeds the runtime, single process. |
| D4 | **v1 screens**: all 7 routes vs. runs + run detail + report | **Three screens**: `/runs`, `/runs/:id`, `/runs/:id/report`. Sandboxes/connections/dashboard are list-CRUD chrome that can follow in days once the core is real. |
| D5 | **Connections**: new named-connections table now vs. per-run raw fields (current CLI reality) | **Defer the table.** Submit form takes api_base/key/model directly (mirrors the CLI); named connections are a convenience layer to add when repeated entry actually hurts. |
| D6 | **Memory preset in run identity**: warn-on-collision vs. add preset to the uniqueness key | **Backend call, decide before the picker ships** — lean warn-on-collision v1 (no migration), revisit if presets become experiment identity in practice. |

## Recommended v1 slice

1. **Contract re-truing, corrected**: real status machine (as proposed) **plus** event
   types re-derived from `serialization.py`'s `updates`/`custom` output — not
   HistoryMiddleware kinds. Delete findings/severity layer. No `tokens` field.
2. **Thin HTTP layer** (FastAPI, embeds Runtime, single process): `GET /api/runs`
   (add `list_runs` to the store), `POST /api/runs` (surface `disposition`),
   `GET /api/runs/:id`, `GET /api/runs/:id/report`, `GET /api/runs/:id/events`
   (cursor replay + SSE live, StreamGap→durable refetch), `GET /api/graph/nodes`
   (static NodeSpec dict). **Redact `llm_api_key` everywhere.**
3. **Screens**: `/runs` (list, status filter, succeeded="reports" chip, submit modal
   handling all four dispositions), `/runs/:id` (static GraphView with select +
   live tones + event badges; NodeInspector with `overview | spec | events` — all
   three real; event stream with node chips + follow/live), `/runs/:id/report`.
   Run header shows attempt/stop_reason, not tokens.
4. **Components**: `Tabs`, `CodeBlock`, `KeyValueList`, `StatusBadge`, `GraphView`,
   `NodeInspector`. Deferred: `Drawer`, `EntityList`, pan/drag, hover-coupling,
   `/sandboxes`, `/connections`, `/capabilities`, `/dash`.

Everything in this slice renders real data through a real API on day one, and every
deferred item has a named trigger for when it earns its way in.
