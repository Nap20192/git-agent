# Wayfinder — product direction, grounded in the real git-agent

This is the decision record for the pivot away from the "vulnhunt" security-scanner mock
toward a UI over the **real** git-agent. Full analyses in `docs/design/` (domain model,
UX proposal, critic review).

## Update: sub-agent system landed (master 68a7c56)

Part of the "forward-looking shell" is no longer forward: master `68a7c56` shipped
`core/agents/subagents/` — a real lead + `task`-tool delegation system (strict star, depth 1), a
`general-purpose` registry sub-agent inheriting the lead's model with a fixed sandbox toolset
(`sandbox_run`, `read_file`), **real token usage** (per-delegation + run-level cumulative), and **tool
receipts** with citation verification. `SubagentStatus` is a real closed enum (`pending | running` →
`completed | failed | cancelled | timed_out`) with an additive `stop_reason` cap. There is still **no
"skills" system** in the backend.

The frontend contract (`src/api/contract.ts`) + mock now reflect this real model instead of the
earlier fiction: the fictional `Skill`/`agent_skill` concept is replaced by a **capabilities catalog**
(`Capability`, sourced from real sub-agent types / sandbox tools / RuntimeFeatures flags / memory
presets), tokens are **real** (not simulated), and the event stream speaks `task_started` /
`task_running` / `task_<terminal>` (from `task_tool.py`) instead of invented `agent_*` events. Still
net-new: the HTTP tier and the named-connection table. Details: `docs/API_CONTRACT.md`,
`docs/openapi.yaml`.

## What git-agent actually is

Not a security scanner. A durable runtime around a **linear LangGraph**: `scan → parse →
report`. `scan` clones the repo and lists files; `parse` AST-walks Python + reads deps +
makes **one** LLM call (`_DESCRIBE_PROMPT`); `report` assembles a JSON **Report** =
repo structure + modules + dependencies + a prose description. Evidence: `core/agents/
graph.py`, `nodes.py`, `migrations/*.sql`, `core/runtime/schemas.py`.

Real run statuses: **`pending | running | succeeded | failed | interrupted`** (terminal =
succeeded/failed/interrupted, absorbing; resume = `failed|interrupted → pending` via claim).
No "pause". Sandboxes are real (`kind ∈ opensandbox|local|ssh`). LLM connection is per-run
(`api_base/key/model`), no saved-connection registry. **Sub-agents, tools, skills and system
prompts do NOT exist in the run path** — `build_agent`/`RuntimeFeatures` scaffolding exists
but is unused. There is **no HTTP API** yet (CLI + library facade only).

## Decisions (from the user)

1. **Direction → forward-looking shell.** Build the full vision now (interactive graph,
   node/sub-agent inspector with system-prompt/tools/skills, skills catalog, connections &
   sandboxes management), because…
2. **Roadmap → multi-subagent, soon.** git-agent is intended to grow into a real
   `build_agent`-based multi-sub-agent system. So the shell is a genuine forward investment,
   not fiction — it must map cleanly onto `build_agent(model, tools, system_prompt)` when
   those nodes land.
3. **Backend → mock for now.** Iterate the UI on the in-memory mock adapter; the thin FastAPI
   layer (~6 routes over the finished `Runtime` facade) comes later. The mock is the
   executable spec and must speak the real backend's dialect.

## How we stay honest while building the future shell

- **Re-true the contract** to the real status machine, Report shape, and event vocabulary
  (`updates`/`custom` chunks, plus forward `agent_*` events for sub-agent runs). Delete the
  findings/severity/CWE layer entirely.
- **The mock seeds both**: a real 3-node pipeline run (procedural nodes whose inspector shows
  the *actual* `_DESCRIBE_PROMPT` and sandbox commands) **and** an example multi-sub-agent run
  (fan-out graph; agent nodes with real-shaped system prompts, tools, skills) to populate the
  forward shell today. Same components render both — no redesign when `build_agent` ships.
- **"Skills" = capabilities, labelled honestly.** The catalog is seeded from the real
  `RuntimeFeatures` flags + memory presets (real names) plus forward agent-skills, each tagged
  `active` vs `planned`.
- **Node inspector tabs** (`overview | system prompt | tools | skills | events`) show real data
  for procedural nodes (spec = prompt + sandbox commands) and full data for agent nodes.

## Screen map (v-forward)

| Route | Screen |
|---|---|
| `/runs` | Runs list — home. Status filter, "reports" = succeeded filter, submit modal (handles all dispositions). |
| `/runs/:id` | Run detail — interactive (pan/drag) graph + node/sub-agent inspector + event stream bound to nodes. |
| `/runs/:id/report` | Report — description, structure, modules, dependencies. |
| `/connections` | Named LLM connections — list/detail/create (mock; backend = new table later). |
| `/sandboxes` | Sandboxes — list/create, kinds opensandbox/local/ssh (ssh disabled). |
| `/skills` | Capabilities & skills catalog — RuntimeFeatures + memory presets + agent skills. |
| `/dash` | Overview aggregates (optional). |

Deleted fantasy: `Finding`, `Severity`, `Confidence`, CWE/CVE, `SeverityTag`, `severity.ts`,
LiveFindings, SeverityFilter, TopWeaknesses, SeverityDistribution.

## New shared components

`Tabs`, `CodeBlock`, `KeyValueList`, `StatusBadge`, `EntityList`, `Drawer` (primitives);
`GraphCanvas` (pan/drag/select SVG surface) + `NodeInspector` (tabbed) in the run feature.
