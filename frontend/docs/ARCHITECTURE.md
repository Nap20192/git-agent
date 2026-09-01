# git-agent frontend — Architecture

React 19 + Vite + TypeScript, react-router-dom v7, CSS Modules. No state/query/UI libraries — the
app is small enough that a tiny `useAsync` + a push stream cover it (see "Swap in TanStack Query"
below for when that stops being true).

## Layers and dependency direction

Dependencies point one way, top to bottom. There is **no global run context** — the chrome is
route-driven and each screen owns its own data.

```
api/        contract types + two adapters (mock, http) behind one interface
  ↓
hooks/      typed data hooks (useAsync, resources, useRunStream)
  ↓
features/ + components/   screen folders, layout chrome, primitives
```

- `src/api/contract.ts` — the wire types (`Run`, `Report`, `RunGraph`/`GraphNode`, `NodeSpec`,
  `RunEvent`, `Connection`, `SandboxSpec`, `Skill`, `MemoryPreset`, …). Single source of truth; the
  narrative spec is `docs/API_CONTRACT.md`.
- `src/api/client.ts` — the `GitAgentApi` interface every component depends on (runs list/get/submit/
  cancel/resume, report, graph, node spec, event stream, connections CRUD+check, sandboxes, skills,
  memory presets).
- `src/api/mock.ts` (+ `demo-data.ts`) / `src/api/http.ts` — the two implementations. Components never
  import either directly; they get the api via `useApi()` from React context (`src/api/index.ts`).
- `src/hooks/` — `useAsync` (minimal fetch state: `data/loading/error/reload`), `resources.ts` (one
  thin hook per endpoint), `useRunStream` (the live-run event reducer).
- `src/app/screens.ts` — the top-nav route registry (drives TopBar tabs).
- `src/components/` — `primitives/` (re-exported from `index.ts`) and `layout/` (AppShell = TopBar +
  `<Outlet/>` + StatusBar).
- `src/features/<area>/` — one folder per area: `runs/`, `connections/`, `sandboxes/`, `skills/`,
  `overview/`. Each holds its screen component(s), sub-components, and a co-located `.module.css`.
  Features import from api/hooks/primitives, never from each other.
- `src/lib/` — pure helpers: `status.ts`, `tone.ts`, `format.ts`.
- `src/styles/` — `tokens.css` (design tokens) + `global.css`.

## Data flow: a run detail view

```
contract.ts types
   → adapter (mock or http)          serves Run/RunGraph snapshots + emits RunEvents
   → useGraph(runId) + useRunStream(runId)
   → RunDetailScreen                 renders GraphCanvas + NodeInspector + EventStream
```

Two channels:

1. **Snapshots** — `useGraph`, `useRun`, `useNodeSpec`, etc. are `useAsync` wrappers over the API,
   fetched on mount / when deps change.
2. **Event stream** — `api.streamRunEvents(runId, {cursor?, onEvent})`. Events carry a monotonic
   per-run `cursor`; clients resume with the last seen cursor and the backend replays from there (the
   mock replays every buffered event with `cursor > cursor`, then goes live; a backend whose buffer no
   longer holds that cursor emits a `gap` event instead of silently dropping history).
   `useRunStream` reduces events into `RunStreamState`: `runStatus`, flat `logs`, per-node
   `eventsByNode` buckets, and a derived per-node `nodeStatus` map. That status map animates the
   graph, so there is no separate polling of `getGraph` for live status.

## Adapter swap: mock vs http

`src/api/index.ts`:

```ts
const mode = import.meta.env.VITE_API ?? "mock";
return mode === "http" ? createHttpApi() : createMockApi();
```

Default is the mock, so `bun dev` works with zero backend. Set `VITE_API=http` to hit the real
backend (`/api` base, proxied in dev via `vite.config.ts` → `http://localhost:8080`; SSE over
`EventSource`).

The mock (`mock.ts` + `demo-data.ts`) is the **executable spec** of the contract. It seeds two runs
the same components render:

- a **live 3-node pipeline run** (`LivePipelineRun`) that advances `scan → parse → report` every
  ~1.8s and streams `RunEvent`s through the exact `streamRunEvents` interface, honouring the status
  machine (terminal-sticky, cancel → interrupted);
- a **static completed multi-sub-agent run** (fan-out graph, agent nodes with real-shaped system
  prompts/tools/skills) that populates the forward shell today.

If a component works against the mock but breaks against the backend, the contract diverged — fix the
shape, not the component.

## The run feature (`src/features/runs/`)

- **GraphCanvas** — interactive SVG surface. Pan by dragging empty space; nodes are draggable and
  selectable. Layout is client-owned: initial positions come from `GraphNode.x/y` percent hints, and
  drags persist to `localStorage` keyed by the node-id set. Node color/icon come from
  `nodeTone`/`nodeIcon` (`src/lib/status.ts`). Scales unchanged from the 3-node pipeline to sub-agent
  fan-out.
- **NodeInspector** — right-panel, tabbed: `overview | system prompt | tools | skills | events`. Reads
  `useNodeSpec(runId, nodeId)`. For procedural nodes (scan/report) the prompt tab honestly shows "no
  LLM prompt (procedural node)" and tools lists the real sandbox commands; for agent nodes it shows the
  `build_agent` system prompt + tools + skills. Skill ids resolve to names via `useSkills`.
- **EventStream** — full-width log bound to the graph by node id, with per-node filter chips and live
  follow; the selected node's rows highlight.

## Design tokens & theming

- `src/styles/tokens.css` — every color, font, and spacing value as a CSS custom property (dark is the
  app default). Components never hardcode a hex value; retheming = overriding variables under a
  `[data-theme]` scope.
- **Tone system** (`src/lib/tone.ts`) — a `Tone` is a named color role (`amber`, `blue`, `crit`,
  `high`, `med`, `low`, `muted`, `dim`, …) that maps 1:1 to a token via `toneVar(tone)` →
  `var(--tone)`. Primitives take a `tone` prop instead of a color.
- **Status system** (`src/lib/status.ts`) — maps domain status onto tone + label + glyph:
  `runTone`/`runLabel`/`runIcon` for `RunStatus`, `nodeTone`/`nodeIcon` for `NodeStatus`, plus
  `RUN_STATUS_ORDER`. This replaced the deleted `severity.ts`.
- **CSS Modules** — layout and per-screen styles live in co-located `*.module.css` files.

## Routing

Two pieces, kept next to each other:

- `src/app/screens.ts` — `SCREENS`: the registry of the five top-level tabs (`/runs`, `/connections`,
  `/sandboxes`, `/skills`, `/dash`) with number-key, id, and label. TopBar renders its nav from this
  array. `DEFAULT_SCREEN = "/runs"`.
- `src/App.tsx` — `createBrowserRouter` with `AppShell` as the layout route and one child `<Route>`
  per screen, including the nested run routes `runs/:id` and `runs/:id/report`; index and `*` both
  redirect to `DEFAULT_SCREEN`. `App.tsx` wires the single provider: `ApiProvider` → router. TopBar
  and StatusBar are route-driven (no global run state).

## Extension points

**Add a screen**
1. Create `src/features/<name>/<Name>Screen.tsx` (+ `.module.css`, sub-components as siblings).
2. Add an entry to `SCREENS` in `src/app/screens.ts` (num, path, id, label).
3. Add the child route in `src/App.tsx`.

**Add an API endpoint/type**
1. Add/extend the types in `src/api/contract.ts` (and mirror in `docs/API_CONTRACT.md`).
2. Add the method to `GitAgentApi` in `src/api/client.ts`.
3. Implement it in **both** `http.ts` (real path) and `mock.ts` (fixtures in `demo-data.ts`).
4. Expose a hook in `src/hooks/resources.ts` (one-liner over `useAsync`) and export it from
   `src/hooks/index.ts`.

**Add a primitive**
1. Create `src/components/primitives/<Name>.tsx` (+ `.module.css` if styled); take `tone`/token-based
   props, no raw colors.
2. Re-export component and props type from `src/components/primitives/index.ts`.
3. Document it in `docs/COMPONENTS.md`.

**Swap in TanStack Query** — `resources.ts` hooks return the `AsyncState` shape
(`data/loading/error/reload`), which maps directly onto `data/isLoading/error/refetch`; rewrite them as
`useQuery` calls and screen code barely changes. `useRunStream` stays as is — it's a push stream, not a
query.

## File tree

```
frontend/src/
├── api/                contract.ts, client.ts (interface), mock.ts + demo-data.ts, http.ts, index.ts (adapter select + context)
├── hooks/              useAsync.ts, resources.ts, useRunStream.ts, index.ts
├── app/                screens.ts (route registry)
├── components/
│   ├── primitives/     Panel, Badge, Button, TextInput, StatusDot, Sparkline, Meter, StatusBadge, Tabs, CodeBlock, KeyValueList, EntityList, Drawer
│   └── layout/         AppShell, TopBar, StatusBar
├── features/
│   ├── runs/           RunsScreen, RunDetailScreen, ReportScreen, GraphCanvas, NodeInspector, EventStream
│   ├── connections/    ConnectionsScreen
│   ├── sandboxes/      SandboxesScreen
│   ├── skills/         SkillsScreen
│   └── overview/       OverviewScreen
├── lib/                status.ts, tone.ts, format.ts
├── styles/             tokens.css, global.css
├── App.tsx             router + ApiProvider
└── main.tsx            entry
```
