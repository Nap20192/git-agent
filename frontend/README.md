# git-agent frontend

UI for **git-agent**: connect GitHub/GitLab repositories, define agent builds (LLM + sandbox
connections, prompt, limits), watch each repository's agent instances react to webhook events,
chat with them, read reports and security findings. Talks only to the Go **hub**
(`backend/`, contract `backend/docs/openapi.yaml`). React 19 + Vite + TypeScript, managed with Bun.

## Quickstart

```sh
bun install
bun dev              # http://localhost:5173 — needs the hub on :8081 (task backend:run or task app)
bun run typecheck    # tsc -b --noEmit  (the required gate)
bun run build        # production bundle
```

`VITE_HUB_API=mock` in `.env.local` runs the UI on the in-memory executable spec
(`src/api/hub/mock.ts`) without a hub. See `frontend.md` for how to work in the codebase.
