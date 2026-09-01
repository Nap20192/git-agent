# git-agent frontend

UI for **git-agent** — the durable runtime around a linear LangGraph pipeline (`scan → parse → report`). It lets you submit runs against a repo, watch a run advance through an interactive node graph with a tabbed node inspector and a live event stream, read the assembled **report** (structure, modules, dependencies, LLM description), and manage LLM **connections**, **sandboxes**, and the **skills/capabilities** catalog, with an **overview** dashboard on top. Dark terminal aesthetic. React 19 + Vite + TypeScript, managed with Bun. Ships against an in-memory mock by default, so it runs with no backend.

> This app was pivoted from an earlier "vulnhunt" security-scanner mock. There are no findings/severity/CWE anymore — see `docs/WAYFINDER.md` for the direction and the honest line between what's real today and what's forward-looking.

## Quickstart

```sh
bun install
bun dev              # http://localhost:5173 — runs on the in-memory MOCK, no backend needed
bun run typecheck    # tsc -b --noEmit  (the required gate)
bun run build        # tsc -b && vite build
```

Set `VITE_API=http` (e.g. `echo 'VITE_API=http' > .env.local`) to hit the real backend instead of the mock. HTTP requests are rooted at `/api`, proxied to `http://localhost:8080` in dev (`vite.config.ts`). The backend is not built yet — the mock is the default and the executable spec.

## Screens

| Route | Screen |
|---|---|
| `/runs` | Runs list (home) — status filter, submit modal |
| `/runs/:id` | Run detail — interactive graph + node inspector + event stream |
| `/runs/:id/report` | Report — description, structure, modules, dependencies |
| `/connections` | Named LLM connections |
| `/sandboxes` | Sandboxes (opensandbox / local / ssh) |
| `/skills` | Capabilities & skills catalog |
| `/dash` | Overview aggregates |

## Project layout

- `src/api/` — the contract (`contract.ts`), the `GitAgentApi` interface (`client.ts`), the two adapters (`mock.ts` + `demo-data.ts`, `http.ts`), and adapter selection + React context (`index.ts`)
- `src/hooks/` — `useAsync` + one resource hook per endpoint (`resources.ts`) + the live-run reducer (`useRunStream.ts`)
- `src/app/` — the screen registry (`screens.ts`)
- `src/features/` — one folder per area: `runs/`, `connections/`, `sandboxes/`, `skills/`, `overview/`
- `src/components/` — `primitives/` (Panel, Badge, Button, …, GraphCanvas lives in features) and `layout/` (AppShell + TopBar + StatusBar)
- `src/lib/` — pure helpers: `status.ts`, `tone.ts`, `format.ts`
- `src/styles/` — `tokens.css` + `global.css`

## Docs

- [docs/WAYFINDER.md](docs/WAYFINDER.md) — product direction + decisions (authoritative)
- [docs/API_CONTRACT.md](docs/API_CONTRACT.md) — the wire contract (endpoints, SSE, status machine)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — layers, adapter swap, streaming, extension recipes
- [docs/COMPONENTS.md](docs/COMPONENTS.md) — primitive + feature component catalog
- `docs/design/` — domain model, UX proposal, critic review
