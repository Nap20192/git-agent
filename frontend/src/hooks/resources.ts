/** Thin resource hooks over the API. Each is a typed useAsync wrapper. */
import { useApi } from "@/api";
import { useAsync } from "./useAsync.ts";

export function useRuns() {
  const api = useApi();
  return useAsync(() => api.listRuns(), []);
}
export function useRun(id: string) {
  const api = useApi();
  return useAsync(() => api.getRun(id), [id]);
}
export function useReports() {
  const api = useApi();
  return useAsync(() => api.listReports(), []);
}
export function useReport(runId: string) {
  const api = useApi();
  return useAsync(() => api.getReport(runId), [runId]);
}
export function useGraph(runId: string) {
  const api = useApi();
  return useAsync(() => api.getGraph(runId), [runId]);
}
export function useNodeSpec(runId: string, nodeId: string | null) {
  const api = useApi();
  return useAsync(() => (nodeId ? api.getNodeSpec(runId, nodeId) : Promise.resolve(null)), [runId, nodeId]);
}
export function useConnections() {
  const api = useApi();
  return useAsync(() => api.listConnections(), []);
}
export function useSandboxes() {
  const api = useApi();
  return useAsync(() => api.listSandboxes(), []);
}
export function useSandboxInstances() {
  const api = useApi();
  return useAsync(() => api.listSandboxInstances(), []);
}
export function useCapabilities() {
  const api = useApi();
  return useAsync(() => api.listCapabilities(), []);
}
export function useMemoryPresets() {
  const api = useApi();
  return useAsync(() => api.listMemoryPresets(), []);
}
