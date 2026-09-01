/**
 * The API surface the UI depends on. Implemented by http.ts over the FastAPI
 * backend (server/app.py, contract in docs/openapi.yaml). Components get this
 * interface via useApi(); they never import an adapter directly.
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
  SandboxSpec,
  SubmitRunRequest,
  SubmitRunResponse,
} from "./contract.ts";

export interface StreamOptions {
  cursor?: number;
  onEvent: (event: RunEvent) => void;
  onError?: (error: Error) => void;
}

export type Unsubscribe = () => void;

export interface GitAgentApi {
  // runs
  listRuns(): Promise<Run[]>;
  getRun(id: string): Promise<Run>;
  submitRun(req: SubmitRunRequest): Promise<SubmitRunResponse>;
  cancelRun(id: string): Promise<Run>;
  /** Resume a failed/interrupted run (resubmit → disposition "resumed"). */
  resumeRun(id: string): Promise<SubmitRunResponse>;

  // report
  getReport(runId: string): Promise<Report>;

  // graph + node specs
  getGraph(runId: string): Promise<RunGraph>;
  getNodeSpec(runId: string, nodeId: string): Promise<NodeSpec>;

  // event stream
  streamRunEvents(runId: string, opts: StreamOptions): Unsubscribe;

  // connections
  listConnections(): Promise<Connection[]>;
  createConnection(input: { name: string; apiBase: string; apiKey: string; model: string }): Promise<Connection>;
  deleteConnection(id: string): Promise<void>;
  checkConnection(id: string): Promise<Connection>;

  // sandboxes
  listSandboxes(): Promise<SandboxSpec[]>;
  createSandbox(input: { name: string; kind: SandboxSpec["kind"]; image?: string; workdir?: string }): Promise<SandboxSpec>;

  // capabilities catalog
  listCapabilities(): Promise<Capability[]>;
  listMemoryPresets(): Promise<MemoryPreset[]>;
}
