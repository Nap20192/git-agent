/**
 * HTTP + SSE adapter for the Go hub backend (backend/docs/openapi.yaml).
 * Session cookie auth; hub endpoints return bare JSON arrays/objects.
 */
import type { ActivityEvent, ChatEvent, FindingFilters, TerminalEvent } from "./contract.ts";
import { UnauthorizedError, type HubApi } from "./client.ts";
import { TRACE_HEADER, newTraceId, setLastTrace, traceTail } from "./trace.ts";

/* Hub base URL. Default "/hub" — vite.config.ts proxies /hub/* to the Go hub
   (:8081), keeping the session cookie same-origin. Set VITE_HUB_URL="" when
   the hub is served from the same origin (prod). */
const BASE = `${import.meta.env.VITE_HUB_URL ?? "/hub"}/api`;

/** Error body per ApiError ({error:{code,message}}); tolerates legacy {error:"…"}.
 *  message carries «trace …abcd» so every inline/status-bar error shows the id;
 *  traceId — full id (status-bar chip copies it). */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code = "error",
    public traceId = "",
  ) {
    super(traceId ? `${message} · ${traceTail(traceId)}` : message);
    this.name = "ApiError";
  }
}

async function apiError(res: Response, traceId: string): Promise<ApiError> {
  let message = res.statusText || `HTTP ${res.status}`;
  let code = "error";
  try {
    const e = (await res.json())?.error;
    if (typeof e === "string") message = e;
    else if (e?.message) ({ message, code = code } = e);
  } catch {
    /* non-JSON error */
  }
  return new ApiError(res.status, message, code, traceId);
}

/** One user action = one trace: fresh X-Trace-Id per request, echoed by the hub
 *  (its value wins if it had to regenerate), logged to console, shown in the status bar. */
async function traced(method: string, path: string, init: RequestInit): Promise<{ res: Response; traceId: string }> {
  let traceId = newTraceId();
  const action = `${method} ${path}`;
  setLastTrace({ id: traceId, action, ok: null });
  console.info(`[hub] ${action} trace=${traceId}`);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers: { ...init.headers, [TRACE_HEADER]: traceId } });
  } catch (e) {
    console.error(`[hub] ${action} trace=${traceId} failed:`, e);
    setLastTrace({ id: traceId, action, ok: false });
    throw new ApiError(0, e instanceof Error ? e.message : "network error", "network", traceId);
  }
  traceId = res.headers.get(TRACE_HEADER) ?? traceId;
  setLastTrace({ id: traceId, action, ok: res.ok });
  if (!res.ok) console.error(`[hub] ${action} trace=${traceId} → ${res.status}`);
  return { res, traceId };
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const { res, traceId } = await traced(init?.method ?? "GET", path, {
    headers: { "content-type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw await apiError(res, traceId);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Same as req, but the body is a file (csv/md export). */
async function reqText(path: string): Promise<string> {
  const { res, traceId } = await traced("GET", path, { credentials: "include" });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw await apiError(res, traceId);
  return res.text();
}

/** ?severity=&category=&eventId=&introducedBy= — only the set keys. */
function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}
const findingsQuery = (f?: FindingFilters, extra: Record<string, string | undefined> = {}) =>
  query({ severity: f?.severity, category: f?.category, eventId: f?.eventId, introducedBy: f?.introducedBy, ...extra });

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
    raiseRepository: (id) => req(`/repositories/${id}/raise`, { method: "POST" }),
    listRepositoryReports: (id) => req(`/repositories/${id}/reports`),

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
    updateLlmConnection: (id, input) => req(`/connections/llm/${id}`, { method: "PUT", body: JSON.stringify(input) }),
    deleteLlmConnection: (id) => req(`/connections/llm/${id}`, { method: "DELETE" }),
    listSandboxConnections: () => req("/connections/sandbox"),
    getDefaults: () => req("/defaults"),
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
    listInstanceFindings: (id, f) => req(`/instances/${id}/findings${findingsQuery(f)}`),
    exportInstanceFindings: (id, format, f) => reqText(`/instances/${id}/findings/export${findingsQuery(f, { format })}`),
    listRepositoryFindings: (id, f) => req(`/repositories/${id}/findings${findingsQuery(f)}`),
    exportRepositoryFindings: (id, format, f) => reqText(`/repositories/${id}/findings/export${findingsQuery(f, { format })}`),

    listRunners: () => req("/runners"),

    listMessages: (instanceId, opts) => {
      const q = new URLSearchParams();
      if (opts?.before) q.set("before", String(opts.before));
      if (opts?.limit) q.set("limit", String(opts.limit));
      const qs = q.toString();
      return req(`/instances/${instanceId}/messages${qs ? `?${qs}` : ""}`);
    },
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
  const method = body != null ? "POST" : "GET";
  const { res, traceId } = await traced(method, path, {
    method,
    headers: body != null ? { "content-type": "application/json" } : undefined,
    credentials: "include",
    body: body != null ? JSON.stringify(body) : undefined,
    signal,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok || !res.body) {
    throw await apiError(res, traceId);
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
