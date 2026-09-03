/**
 * Hub API entry point. Mock by default (backend still being written);
 * VITE_HUB_API=http in .env.local switches to the real Go backend.
 */
import { createContext, useContext } from "react";
import type { HubApi } from "./client.ts";
import { createHttpHubApi } from "./http.ts";
import { createMockHubApi } from "./mock.ts";

export function createHubApi(): HubApi {
  return import.meta.env.VITE_HUB_API === "http" ? createHttpHubApi() : createMockHubApi();
}

export const hubApi: HubApi = createHubApi();

const HubApiContext = createContext<HubApi>(hubApi);
export const HubApiProvider = HubApiContext.Provider;

export function useHubApi(): HubApi {
  return useContext(HubApiContext);
}

export * from "./contract.ts";
export { UnauthorizedError } from "./client.ts";
export type { HubApi } from "./client.ts";
