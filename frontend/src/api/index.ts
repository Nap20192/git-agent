/**
 * API entry point: the real HTTP backend (see docs/openapi.yaml), exposed via
 * React context.
 */
import { createContext, useContext } from "react";
import type { GitAgentApi } from "./client.ts";
import { createHttpApi } from "./http.ts";

export function createApi(): GitAgentApi {
  return createHttpApi();
}

export const api: GitAgentApi = createApi();

const ApiContext = createContext<GitAgentApi>(api);
export const ApiProvider = ApiContext.Provider;

export function useApi(): GitAgentApi {
  return useContext(ApiContext);
}

export * from "./contract.ts";
export type { GitAgentApi, StreamOptions, Unsubscribe } from "./client.ts";
