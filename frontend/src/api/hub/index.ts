/**
 * Hub API entry point: the real Go hub by default; VITE_HUB_API=mock in
 * .env.local switches to the in-memory executable spec (src/api/hub/mock.ts).
 */
import { createContext, useContext } from "react";
import type { HubApi } from "./client.ts";
import { createHttpHubApi } from "./http.ts";
import { createMockHubApi } from "./mock.ts";

export function createHubApi(): HubApi {
  return import.meta.env.VITE_HUB_API === "mock" ? createMockHubApi() : createHttpHubApi();
}

export const hubApi: HubApi = createHubApi();

const HubApiContext = createContext<HubApi>(hubApi);
export const HubApiProvider = HubApiContext.Provider;

export function useHubApi(): HubApi {
  return useContext(HubApiContext);
}

export * from "./contract.ts";
export { UnauthorizedError } from "./client.ts";
export { ApiError } from "./http.ts";
export { traceTail, useLastTrace } from "./trace.ts";
export type { HubApi } from "./client.ts";
