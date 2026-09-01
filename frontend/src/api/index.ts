/**
 * API entry point. Selects the adapter (mock vs http) and exposes it via React
 * context. VITE_API=http hits the real backend; default is the mock.
 */
import { createContext, useContext } from "react";
import type { GitAgentApi } from "./client.ts";
import { createMockApi } from "./mock.ts";
import { createHttpApi } from "./http.ts";

export function createApi(): GitAgentApi {
  const mode = import.meta.env.VITE_API ?? "mock";
  return mode === "http" ? createHttpApi() : createMockApi();
}

export const api: GitAgentApi = createApi();

const ApiContext = createContext<GitAgentApi>(api);
export const ApiProvider = ApiContext.Provider;

export function useApi(): GitAgentApi {
  return useContext(ApiContext);
}

export * from "./contract.ts";
export type { GitAgentApi, StreamOptions, Unsubscribe } from "./client.ts";
