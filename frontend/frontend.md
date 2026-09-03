# frontend.md — how to work in this app

Practical guide for developing the **git-agent** frontend. Read this before opening a PR.

The UI is a client of the Go **hub** only (`backend/`, contract `backend/docs/openapi.yaml`,
camelCase, authoritative). Screens: `/repos` (home: connected repositories), `/repos/:id`
(the agents' home — AGENTS panel of subscriptions/instances, run agent CTA, chat, journal),
`/instances/:id` (playground: activity graph, terminal), `/builds`, `/account`, `/dash`.

## 1. Stack

| Concern | Choice |
|---|---|
| Runtime / package manager | **Bun** |
| Build | **Vite** (native TS, CSS Modules, HMR) |
| UI | **React 19**, function components + hooks only |
| Language | **TypeScript (strict)**; `any` is banned |
| Routing | **react-router-dom v7**, one route per screen (`src/App.tsx`) |
| Styling | **CSS Modules + tokens** (`src/styles/`, vk-colors) |
| Server state | custom hooks over the typed `HubApi` (`src/hooks/hub.ts`) |

No component library, no CSS framework, no state-management library.

## 2. Run it

```bash
bun install
bun dev              # http://localhost:5173
bun run typecheck    # tsc -b --noEmit — the primary gate, must be clean
bun run build        # tsc -b && vite build
```

`bun dev` expects the hub on `:8081` (`task backend:run`, or `task app` for everything).
Requests go to `/hub/api/*`; `vite.config.ts` proxies `/hub/*` to the hub so the session cookie
stays same-origin. `VITE_HUB_API=mock` in `.env.local` swaps in the in-memory executable spec
(`src/api/hub/mock.ts`) — keep it in sync with the openapi contract when you touch the wire.

## 3. Where things go

```
src/
  api/hub/        the ONLY place that knows the wire format
    contract.ts     wire types (mirror of backend/docs/openapi.yaml)
    client.ts       HubApi interface + UnauthorizedError
    http.ts         real adapter (fetch + SSE; errors → ApiError {status, code, message})
    mock.ts         executable spec for offline dev
  hooks/hub.ts    data hooks over HubApi (useAsync-based)
  features/hub/   one file per screen + ui.tsx (shared bits: errMsg, panels) + HubGate (auth shell)
  styles/         global.css, vk-colors.css, vk-fonts.css
  lib/theme.ts    theme toggle
docs/design/git-agent-hub.dc.html   the design reference the hub screens follow
```

Rules: new endpoint → `contract.ts` + `client.ts` + `http.ts` + `mock.ts` in one change; screens
never call `fetch`; a failed user action goes through `useShell().fail(e, fallback)` — it renders
the backend message + `X-Trace-Id` in the `ErrorBanner` over the screen (inline streams may still
use `errMsg`); a `401` throws `UnauthorizedError` and `HubGate` sends the user to sign in.
Terminology (CONTEXT.md): **sandbox connection** = where/from which image the hub creates,
**sandbox instance** = the live container of one agent, auto-created on run — never ask the user
to bind one; `Onboarding` in `ui.tsx` is the 3-step checklist shown while setup is incomplete.

## 4. How to test

- **Typecheck** is the required gate (`bun run typecheck`).
- **Manual**: run against the real hub (`task app`) or the mock (`VITE_HUB_API=mock`).
- No unit-test runner is wired yet; add `bun test` when the first pure helper needs it.

## 5. PR checklist

- [ ] `bun run typecheck` clean
- [ ] wire change mirrored in contract/client/http/mock
- [ ] no new dependency without a reason in the PR
