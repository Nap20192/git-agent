/**
 * HTTP + SSE adapter for the Go hub backend (backend/docs/openapi.yaml).
 * Session cookie auth; hub endpoints return bare JSON arrays/objects.
 */
import type { ActivityEvent, ChatEvent, TerminalEvent } from "./contract.ts";
import { UnauthorizedError, type HubApi } from "./client.ts";

/* Hub base URL. Default "/hub" — vite.config.ts proxies /hub/* to the Go hub
   (:8081), keeping the session cookie same-origin. Set VITE_HUB_URL="" when
   the hub is served from the same origin (prod). */
const BASE = `${import.meta.env.VITE_HUB_URL ?? "/hub"}/api`;

/** Error body per ApiError ({error:{code,message}}); tolerates legacy {error:"…"}. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code = "error",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiError(res: Response): Promise<ApiError> {
  let message = res.statusText || `HTTP ${res.status}`;
  let code = "error";
  try {
    const e = (await res.json())?.error;
    if (typeof e === "string") message = e;
    else if (e?.message) ({ message, code = code } = e);
  } catch {
    /* non-JSON error */
  }
  return new ApiError(res.status, message, code);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw await apiError(res);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function createHttpHubApi(): HubApi {
  return {
    me: () => req("/me"),
    async login(provider) {
      window.location.assign(`${BASE}/auth/${provider}/login`);
    },
    async logout() {
      await req<void>("/auth/logout", { method: "POST" });
    },
    listIdentities: () => req("/identities"),
    deleteIdentity: (id) => req(`/identities/${id}`, { method: "DELETE" }),
    listIdentityRepos: (id) => req(`/identities/${id}/repos`),

    listRepositories: () => req("/repositories"),
    connectRepository: (input) => req("/repositories", { method: "POST", body: JSON.stringify(input) }),
    setRepositoryBuild: (id, buildId) =>
      req(`/repositories/${id}`, { method: "PATCH", body: JSON.stringify({ buildId }) }),
    disconnectRepository: (id) => req(`/repositories/${id}`, { method: "DELETE" }),
    listRepositoryEvents: (id) => req(`/repositories/${id}/events`),
    triggerRepository: (id, input) =>
      req(`/repositories/${id}/trigger`, { method: "POST", body: JSON.stringify(input ?? {}) }),

    listSubscriptions: (repositoryId) => req(`/repositories/${repositoryId}/subscriptions`),
    createSubscription: (repositoryId, input) =>
      req(`/repositories/${repositoryId}/subscriptions`, { method: "POST", body: JSON.stringify(input) }),
    deleteSubscription: (id) => req(`/subscriptions/${id}`, { method: "DELETE" }),

    listBuilds: () => req("/builds"),
    createBuild: (input) => req("/builds", { method: "POST", body: JSON.stringify(input) }),
    updateBuild: (id, input) => req(`/builds/${id}`, { method: "PATCH", body: JSON.stringify(input) }),
    deleteBuild: (id) => req(`/builds/${id}`, { method: "DELETE" }),

    listLlmConnections: () => req("/connections/llm"),
    createLlmConnection: (input) => req("/connections/llm", { method: "POST", body: JSON.stringify(input) }),
    deleteLlmConnection: (id) => req(`/connections/llm/${id}`, { method: "DELETE" }),
    listSandboxConnections: () => req("/connections/sandbox"),
    createSandboxConnection: (input) => req("/connections/sandbox", { method: "POST", body: JSON.stringify(input) }),
    deleteSandboxConnection: (id) => req(`/connections/sandbox/${id}`, { method: "DELETE" }),

    listSandboxInstances: () => req("/sandbox-instances"),
    createSandboxInstance: (input) =>
      req("/sandbox-instances", { method: "POST", body: JSON.stringify(input) }),
    killSandboxInstance: (id) => req(`/sandbox-instances/${id}`, { method: "DELETE" }),
    setInstanceSandbox: (instanceId, sandboxInstanceId) =>
      req(`/instances/${instanceId}/sandbox`, {
        method: "POST",
        body: JSON.stringify({ sandboxInstanceId }),
      }),

    listInstances: (repositoryId) =>
      req(`/instances${repositoryId != null ? `?repositoryId=${repositoryId}` : ""}`),
    getInstance: (id) => req(`/instances/${id}`),
    stopInstance: (id) => req(`/instances/${id}/stop`, { method: "POST" }),
    raiseInstance: (id) => req(`/instances/${id}/raise`, { method: "POST" }),
    resumeInstance: (id) => req(`/instances/${id}/resume`, { method: "POST" }),
    listInstanceReports: (id) => req(`/instances/${id}/reports`),
    listInstanceFindings: (id) => req(`/instances/${id}/findings`),

    listRunners: () => req("/runners"),

    chat: (instanceId, message, onEvent) =>
      streamSSE<ChatEvent>(`/instances/${instanceId}/chat`, { message }, onEvent),

    terminal: (instanceId, command, onEvent) =>
      streamSSE<TerminalEvent>(`/instances/${instanceId}/terminal`, { command }, onEvent),

    activity: (instanceId, eventId, onEvent, signal) =>
      streamSSE<ActivityEvent>(
        `/instances/${instanceId}/activity${eventId != null ? `?eventId=${eventId}` : ""}`,
        null,
        onEvent,
        signal,
      ),
  };
}

/** Hit an SSE endpoint (POST with body, GET without) and feed each `data: <JSON>` frame to onEvent. */
async function streamSSE<E>(
  path: string,
  body: unknown,
  onEvent: (e: E) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: body != null ? "POST" : "GET",
    headers: body != null ? { "content-type": "application/json" } : undefined,
    credentials: "include",
    body: body != null ? JSON.stringify(body) : undefined,
    signal,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok || !res.body) {
    throw await apiError(res);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as E);
      } catch {
        /* skip malformed frame */
      }
    }
  }
}
