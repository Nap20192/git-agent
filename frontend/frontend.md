# frontend.md — how to work in this app

Practical guide for developing the **git-agent** frontend: how to run it, how to write code that
fits, what to reach for, and how to test. Read this before opening a PR.

This is a UI over git-agent's durable runtime around a linear LangGraph (`scan → parse → report`):
submit runs, watch a run's interactive node graph + inspector + event stream, read the report, and
manage connections, sandboxes, and the skills/capabilities catalog. (It was pivoted off an earlier
"vulnhunt" security-scanner mock — there are no findings/severity anymore; see `docs/WAYFINDER.md`.)

Deeper references:
- `docs/WAYFINDER.md` — product direction + the honest line between real-today and forward-looking.
- `docs/API_CONTRACT.md` — the backend↔frontend wire contract (endpoints, SSE, status machine).
- `docs/ARCHITECTURE.md` — layers, data flow, extension recipes.
- `docs/COMPONENTS.md` — the primitive + feature component catalog.

---

## 1. Stack

| Concern | Choice | Why |
|---|---|---|
| Runtime / package manager | **Bun** | fast install + dev server, project standard |
| Build | **Vite** | native TS, CSS Modules, fast HMR |
| UI | **React 19** | function components + hooks only |
| Language | **TypeScript (strict)** | contract-driven; `any` is banned |
| Routing | **react-router-dom v7** | one route per screen |
| Styling | **CSS Modules + design tokens** | scoped styles, themable via CSS vars |
| Server state | **custom hooks over a typed API** | no query lib yet — see §7 |

No component library, no CSS framework, no state-management library. If you think you need one, check
§5 first — the answer is usually "a hook and a token."

---

## 2. Run it

```bash
bun install          # once
bun dev              # http://localhost:5173 — runs on the in-memory MOCK, no backend needed
bun run typecheck    # tsc -b --noEmit  (the primary gate — must be clean)
bun run build        # tsc -b && vite build  (production bundle)
bun run preview      # serve the built bundle
```

By default the app talks to the **mock adapter** — a simulated live pipeline run that advances
`scan → parse → report` and streams events, plus a static multi-sub-agent run. Zero backend needed.

To point at the real git-agent backend (once it exists):

```bash
echo 'VITE_API=http' > .env.local   # /api proxied to http://localhost:8080 (see vite.config.ts)
bun dev
```

### Hub (Go backend)

The `/repos`, `/repos/:id`, `/builds`, `/account` screens talk to the **Go hub** service
(contract: `backend/docs/openapi.yaml`, camelCase, authoritative) through a separate API layer in
`src/api/hub/` — same mock-as-spec pattern: `contract.ts` (wire types) + `client.ts` (`HubApi`) +
`mock.ts` (executable spec, **default**) + `http.ts` (real adapter). Switch with
`VITE_HUB_API=http` in `.env.local` once the hub is running. Hooks live in `src/hooks/hub.ts`;
screens in `src/features/hub/` behind `HubGate` (OAuth sign-in via `GET /api/me`, Railway model).
The chat SSE frame shape (`ChatEvent`) is the frontend's provisional spec — the openapi contract
only says "события chat"; keep mock and backend in sync when it lands.

**UX model: repo-centric.** The Экземпляр Агента is 1:1 with a repository, so there is no
instances screen — the repo page (`/repos/:id`) is the agent's home: presence (awake/asleep,
the breathing-halo signature element), chat, Событие journal, reports, findings, and settings
(Сборка binding, disconnect). The repos list is a card grid; connecting a repo is a drawer flow
(identity → provider repo → connect).

**Claude design island.** Hub screens render inside `HubGate`'s shell (`data-theme="claude"`),
a scope in `tokens.css`: ivory surfaces, coral accent (`--amber` remapped), serif display
(`--font-display`), sans UI (`--font-ui`), rounded shape (`--radius`); mono is reserved for
machine facts (shas, refs, keys — `.mono` in `hub.module.css`). Terminal screens keep the base
tokens (`--radius: 0`), so primitives round only inside the island. To retheme the whole app the
same way, move the attribute up to `<html>`.

---

## 3. Screens & where things go

Screens: `/runs` (list, home) · `/runs/:id` (detail: graph + inspector + stream) ·
`/runs/:id/report` · `/connections` · `/sandboxes` · `/skills` · `/dash` (overview).

```
src/
  api/            the contract + adapters — the ONLY place that knows the wire format
    contract.ts     all wire types (Run, Report, RunGraph, NodeSpec, RunEvent, …) — source of truth
    client.ts       the GitAgentApi interface every screen depends on
    http.ts         real backend adapter (REST + SSE)
    mock.ts         in-memory adapter (the "executable spec")
    demo-data.ts    reference fixtures used by the mock
    index.ts        adapter selection + ApiProvider/useApi
  hooks/          thin React hooks over the API (useRuns, useGraph, useRunStream, …)
  app/            screens.ts (route registry)
  lib/            pure helpers (status, tone, format) — no React
  components/
    primitives/     reusable, dumb building blocks (Panel, Badge, Button, Tabs, …)
    layout/         app chrome (TopBar, StatusBar, AppShell) — route-driven
  features/       one folder per area: runs, connections, sandboxes, skills, overview
  styles/         tokens.css (design tokens) + global.css
```

**Rule of thumb for a new file:** pure logic → `lib/`. Reusable visual atom → `components/primitives/`.
Screen-specific → `features/<area>/`. Data access → a hook in `hooks/` over `api/`.

Dependency direction is one-way: `api → hooks → features/components`. There is **no global run
context** — the chrome is route-driven and each screen owns its data. Nothing in `components/` or
`features/` imports another feature; shared pieces move down to `primitives`/`lib`.

---

## 4. How to write code here

**Components.** Function components, named exports (never `default` — `App.tsx` imports by name).
Split repeated markup into small typed sub-components in the same feature folder.

**Styling.** Static styles → a co-located `*.module.css`. Inline `style={{}}` only for data-dependent
values (a computed width, a tone color). **Never hardcode a hex color** — use a token or the tone
system:

```tsx
import { toneVar } from "@/lib/tone.ts";
<span style={{ color: toneVar("crit") }}>…</span>   // ✅  var(--crit)
<span style={{ color: "#ff3d6e" }}>…</span>          // ❌  bypasses theming
```

All colors, spacing, fonts live in `src/styles/tokens.css`. Retheming = override those variables under
a `[data-theme]` scope; nothing else changes.

**Types.** Import wire types from `@/api`. Don't redefine a shape that already exists in `contract.ts`.
`strict` + `noUnusedLocals` + `noUnusedParameters` are on — dead code fails the build.

**Data.** Never call `fetch` from a component. Read through a hook:

```tsx
const { data: graph, loading, error } = useGraph(runId);
```

For a run's live stream, use `useRunStream(runId)` — it subscribes, reduces events, and returns
`{ runStatus, logs, eventsByNode, nodeStatus }`.

**Imports.** Use the `@/` alias (= `src/`). Barrel imports for primitives:
`import { Panel, Badge, Button } from "@/components/primitives";`.

---

## 5. What to use (don't reinvent)

| Need | Use |
|---|---|
| A bordered card / section | `Panel` + `PanelHeader` |
| Status pill | `Badge`, or `StatusBadge` for a `RunStatus` |
| A button (fill/outline/ghost) | `Button variant=…` |
| Terminal-style text field | `TextInput` |
| Tabbed panel | `Tabs` |
| Code / prompt block with copy | `CodeBlock` |
| Key/value rows | `KeyValueList` |
| A list-page table (click, select, empty) | `EntityList` |
| Right-side slide-over | `Drawer` |
| Live status dot (pulse/glow) | `StatusDot` |
| Tiny trend line / percent bar | `Sparkline` / `Meter` |
| Color from a role name | `toneVar(tone)` |
| Status → tone/label/icon | `runTone`/`runLabel`/`runIcon`, `nodeTone`/`nodeIcon` (`@/lib/status.ts`) |
| mm:ss, token, spark formatting | `@/lib/format.ts` |
| Lists of runs / connections / sandboxes / skills / presets | `useRuns` / `useConnections` / `useSandboxes` / `useSkills` / `useMemoryPresets` |
| A single run / report / graph / node spec | `useRun` / `useReport` / `useGraph` / `useNodeSpec` |
| A run's live event stream | `useRunStream` |
| Interactive run graph / node inspector / log | `GraphCanvas` / `NodeInspector` / `EventStream` (`features/runs/`) |
| Navigate between screens | `useNavigate()` from react-router-dom |

---

## 6. Common recipes

**Add a screen.**
1. `src/features/<area>/<Name>Screen.tsx` → `export function <Name>Screen()`.
2. Add an entry to `src/app/screens.ts` (num, path, id, label) — this drives the top-bar tab.
3. Add a `<Route path="…" element={<…Screen />} />` in `src/App.tsx`.

**Add an API endpoint / type.**
1. Add the type to `src/api/contract.ts`.
2. Add the method to the `GitAgentApi` interface in `src/api/client.ts`.
3. Implement it in **both** `http.ts` (real path) and `mock.ts` (fixtures in `demo-data.ts`) — the
   mock must stay a faithful stand-in or the app diverges between adapters.
4. Expose a hook in `src/hooks/resources.ts` if screens need it.

**Add a primitive.**
1. `src/components/primitives/Thing.tsx` (+ `Thing.module.css`), typed props interface exported.
2. Re-export from `src/components/primitives/index.ts`.
3. Document it in `docs/COMPONENTS.md`.

---

## 7. How to test

Three layers, cheapest first.

### a. Typecheck — the current required gate
```bash
bun run typecheck    # must be clean before every commit/PR
bun run build        # catches anything tsc -b misses + verifies the bundle
```
The strict compiler is the non-negotiable gate today.

### b. Manual / visual — against the mock
```bash
bun dev
```
Walk the screens. The mock advances the live pipeline run every ~1.8s, so you can watch the graph
animate, the event stream fill, and status transitions land; the static multi-sub-agent run exercises
the forward shell (agent nodes, inspector tabs). This is how you verify layout and interactions.

### c. Unit tests — recommended, not yet wired
Use **Vitest** (Vite-native) + **@testing-library/react**:
```bash
bun add -d vitest @testing-library/react @testing-library/jest-dom jsdom
```
Add `"test": "vitest"` to `package.json` and a `test: { environment: "jsdom" }` block in
`vite.config.ts`.

Worth testing, in priority order (test the logic, not the pixels):

1. **The stream reducer** — `reduce` / `nodeStatusFromEvent` in `src/hooks/useRunStream.ts`. Feed it a
   sequence of `RunEvent`s and assert the accumulated `logs`, `eventsByNode`, `nodeStatus`, and
   `runStatus`. This is the trickiest logic in the app.
2. **The mock adapter** — `src/api/mock.ts` *is* the contract's executable spec: assert that a
   submitted run advances phases, that terminal status is sticky, that cancel → `interrupted`, and
   that submit dispositions (`created`/`attached`/`resumed`/`already_succeeded`) are correct.
3. **Pure helpers** — `src/lib/format.ts` (`elapsed`, `sparkPoints`, `tokensLabel`) and
   `src/lib/status.ts` (`runTone`/`nodeTone`). Trivial, high value, no DOM.
4. **Components** — only where there's branching. Render with Testing Library, assert behavior.

Don't chase coverage on the fixtures in `demo-data.ts` — they're data, not logic.

---

## 8. PR checklist

- [ ] `bun run typecheck` clean, `bun run build` succeeds.
- [ ] No hardcoded colors — tokens/tone only.
- [ ] New wire shapes added to `contract.ts` **and** implemented in both adapters.
- [ ] New reusable UI lives in `primitives/`, not copied between features.
- [ ] Component/endpoint documented in the relevant `docs/*.md`.
- [ ] Verified in the browser against the mock.
