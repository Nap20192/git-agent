/** Thin resource hooks over the hub API (mirrors resources.ts). */
import { useHubApi } from "@/api/hub";
import { useAsync } from "./useAsync.ts";

export function useMe() {
  const api = useHubApi();
  return useAsync(() => api.me(), []);
}
export function useIdentities() {
  const api = useHubApi();
  return useAsync(() => api.listIdentities(), []);
}
export function useIdentityRepos(identityId: number | null) {
  const api = useHubApi();
  return useAsync(
    () => (identityId != null ? api.listIdentityRepos(identityId) : Promise.resolve(null)),
    [identityId],
  );
}
export function useHubRepositories() {
  const api = useHubApi();
  return useAsync(() => api.listRepositories(), []);
}
export function useRepoEvents(repositoryId: number | null) {
  const api = useHubApi();
  return useAsync(
    () => (repositoryId != null ? api.listRepositoryEvents(repositoryId) : Promise.resolve(null)),
    [repositoryId],
  );
}
export function useSubscriptions(repositoryId: number) {
  const api = useHubApi();
  return useAsync(() => api.listSubscriptions(repositoryId), [repositoryId]);
}
export function useBuilds() {
  const api = useHubApi();
  return useAsync(() => api.listBuilds(), []);
}
export function useLlmConnections() {
  const api = useHubApi();
  return useAsync(() => api.listLlmConnections(), []);
}
export function useSandboxConnections() {
  const api = useHubApi();
  return useAsync(() => api.listSandboxConnections(), []);
}
export function useInstances() {
  const api = useHubApi();
  return useAsync(() => api.listInstances(), []);
}
export function useInstance(id: number) {
  const api = useHubApi();
  return useAsync(() => api.getInstance(id), [id]);
}
export function useInstanceReports(id: number) {
  const api = useHubApi();
  return useAsync(() => api.listInstanceReports(id), [id]);
}
export function useInstanceFindings(id: number) {
  const api = useHubApi();
  return useAsync(() => api.listInstanceFindings(id), [id]);
}
export function useRunners() {
  const api = useHubApi();
  return useAsync(() => api.listRunners(), []);
}
