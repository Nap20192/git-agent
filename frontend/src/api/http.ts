/**
 * HTTP + SSE adapter for the git-agent FastAPI backend (server/app.py).
 * Endpoint shapes: docs/openapi.yaml. Base path "/api", proxied in dev to
 * :8080 (vite.config.ts). This is the only adapter — the UI always talks to
 * the real backend.
 */
import type {
  Capability,
  Connection,
  MemoryPreset,
  NodeSpec,
  Report,
  Run,
  RunEvent,
  RunGraph,
  RunListResponse,
  SandboxSpec,
  SubmitRunRequest,
  SubmitRunResponse,
} from "./contract.ts";
import type { GitAgentApi, StreamOptions, Unsubscribe } from "./client.ts";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      message = (await res.json())?.error?.message ?? message;
    } catch {
      /* non-JSON error */
    }
    throw new Error(`${res.status} ${message}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function createHttpApi(): GitAgentApi {
  return {
    async listRuns() {
      return (await req<RunListResponse>("/runs")).runs;
    },
    getRun: (id) => req<Run>(`/runs/${id}`),
    submitRun: (b: SubmitRunRequest) =>
      req<SubmitRunResponse>("/runs", { method: "POST", body: JSON.stringify(b) }),
    cancelRun: (id) => req<Run>(`/runs/${id}/cancel`, { method: "POST" }),
    resumeRun: (id) => req<SubmitRunResponse>(`/runs/${id}/resume`, { method: "POST" }),
    deleteRun: async (id) => {
      await req<void>(`/runs/${id}`, { method: "DELETE" });
    },

    getReport: (runId) => req<Report>(`/runs/${runId}/report`),
    getGraph: (runId) => req<RunGraph>(`/runs/${runId}/graph`),
    getNodeSpec: (runId, nodeId) => req<NodeSpec>(`/runs/${runId}/nodes/${nodeId}`),

    streamRunEvents(runId, opts: StreamOptions): Unsubscribe {
      const url = `${BASE}/runs/${runId}/events` + (opts.cursor != null ? `?cursor=${opts.cursor}` : "");
      const es = new EventSource(url);
      es.onmessage = (e) => {
        try {
          opts.onEvent(JSON.parse(e.data) as RunEvent);
        } catch (err) {
          opts.onError?.(err as Error);
        }
      };
      es.onerror = () => opts.onError?.(new Error("event stream error"));
      return () => es.close();
    },

    async listConnections() {
      return (await req<{ connections: Connection[] }>("/connections")).connections;
    },
    createConnection: (input) => req<Connection>("/connections", { method: "POST", body: JSON.stringify(input) }),
    deleteConnection: async (id) => {
      await req<void>(`/connections/${id}`, { method: "DELETE" });
    },
    checkConnection: (id) => req<Connection>(`/connections/${id}/check`, { method: "POST" }),

    async listSandboxes() {
      return (await req<{ sandboxes: SandboxSpec[] }>("/sandboxes")).sandboxes;
    },
    createSandbox: (input) => req<SandboxSpec>("/sandboxes", { method: "POST", body: JSON.stringify(input) }),

    async listCapabilities() {
      return (await req<{ capabilities: Capability[] }>("/capabilities")).capabilities;
    },
    async listMemoryPresets() {
      return (await req<{ presets: MemoryPreset[] }>("/memory-presets")).presets;
    },
  };
}
