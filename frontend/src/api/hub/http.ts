/**
 * HTTP + SSE adapter for the Go hub backend (backend/docs/openapi.yaml).
 * Session cookie auth; hub endpoints return bare JSON arrays/objects.
 */
import type { ChatEvent } from "./contract.ts";
import { UnauthorizedError, type HubApi } from "./client.ts";

/* Hub base URL. Default "" = same-origin /api (vite proxies that to the
   Python gateway :8080). To hit the Go hub (:8081) in dev, set
   VITE_HUB_URL=/hub — vite.config.ts proxies /hub/* there, keeping the
   session cookie same-origin. */
const BASE = `${import.meta.env.VITE_HUB_URL ?? ""}/api`;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (res.status === 401) throw new UnauthorizedError();
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
    listInstanceReports: (id) => req(`/instances/${id}/reports`),
    listInstanceFindings: (id) => req(`/instances/${id}/findings`),

    listRunners: () => req("/runners"),

    async chat(instanceId, message, onEvent) {
      const res = await fetch(`${BASE}/instances/${instanceId}/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ message }),
      });
      if (res.status === 401) throw new UnauthorizedError();
      if (!res.ok || !res.body) {
        let m = res.statusText;
        try {
          m = (await res.json())?.error?.message ?? m;
        } catch {
          /* non-JSON */
        }
        throw new Error(`${res.status} ${m}`);
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
            onEvent(JSON.parse(line.slice(6)) as ChatEvent);
          } catch {
            /* skip malformed frame */
          }
        }
      }
    },
  };
}
