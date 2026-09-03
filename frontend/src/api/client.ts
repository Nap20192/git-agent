/**
 * The API surface the UI depends on. Implemented by http.ts over the FastAPI
 * backend (server/app.py, contract in docs/openapi.yaml). Components get this
 * interface via useApi(); they never import an adapter directly.
 */
import type {
  Capability,
  Connection,
  Finding,
  MemoryPreset,
  NodeSpec,
  Report,
  ReportCard,
  ReportMeta,
  Run,
  RunEvent,
  RunGraph,
  SandboxSpec,
  SandboxInstance,
  ChatTurn,
  RunLimits,
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
  /** Resume/continue a failed/interrupted run; optional new limits raise the budget. */
  resumeRun(id: string, limits?: RunLimits): Promise<SubmitRunResponse>;
  /** Delete a terminal run (history + checkpoints). Active runs are refused. */
  deleteRun(id: string): Promise<void>;

  // report
  listReports(): Promise<ReportCard[]>;
  getReport(runId: string): Promise<Report>;
  /** Live findings from report_finding events — available before the run finishes. */
  getFindings(runId: string): Promise<{ findings: Finding[]; meta: ReportMeta }>;

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
  // sandbox instances (live/dead, killable)
  listSandboxInstances(): Promise<SandboxInstance[]>;
  killSandboxInstance(id: string): Promise<SandboxInstance>;

  // capabilities catalog
  listCapabilities(): Promise<Capability[]>;
  listMemoryPresets(): Promise<MemoryPreset[]>;

  // post-run chat (agent runs) — history + streamed send
  chatHistory(runId: string): Promise<ChatTurn[]>;
  sendChat(runId: string, message: string, onEvent: (event: RunEvent) => void): Promise<void>;
}
