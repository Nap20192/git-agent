/**
 * Live-run view-model. Subscribes to the run event stream and accumulates it into
 * the log list, per-node event buckets, and a derived per-node status map (used to
 * animate the graph). Node status is derived from the event vocabulary — the real
 * backend emits LangGraph `updates` chunks keyed by node name, plus `agent_*`
 * events for sub-agent runs — so no separate polling of the graph is needed.
 */
import { useEffect, useRef, useState } from "react";
import { useApi } from "@/api";
import type { NodeStatus, RunEvent, RunStatus } from "@/api";

export interface RunStreamState {
  runStatus: RunStatus | null;
  logs: RunEvent[];
  eventsByNode: Record<string, RunEvent[]>;
  nodeStatus: Record<string, NodeStatus>;
}

const EMPTY: RunStreamState = { runStatus: null, logs: [], eventsByNode: {}, nodeStatus: {} };

export function useRunStream(runId: string): RunStreamState {
  const api = useApi();
  const [state, setState] = useState<RunStreamState>(EMPTY);
  const cursor = useRef(0);

  useEffect(() => {
    let alive = true;
    setState(EMPTY);
    cursor.current = 0;
    api.getRun(runId).then((r) => alive && setState((s) => ({ ...s, runStatus: r.status }))).catch(() => {});
    const unsub = api.streamRunEvents(runId, {
      onEvent: (e) => {
        cursor.current = Math.max(cursor.current, e.cursor);
        setState((s) => reduce(s, e));
      },
    });
    return () => {
      alive = false;
      unsub();
    };
  }, [api, runId]);

  return state;
}

function nodeStatusFromEvent(e: RunEvent): NodeStatus | null {
  // Trust the structured payload — the backend leaves `message` empty for these,
  // so the old text-matching path never saw "completed".
  const d = e.data;
  if (d?.kind === "node_status") return d.status; // LangGraph updates chunk: node done
  if (d?.kind === "task_started") return "running";
  if (d?.kind === "task_step") return "running";
  if (d?.kind === "task_terminal") return d.status === "completed" ? "completed" : "error";
  return null;
}

function reduce(s: RunStreamState, e: RunEvent): RunStreamState {
  const logs = [...s.logs, e];
  const eventsByNode = { ...s.eventsByNode };
  if (e.agent) eventsByNode[e.agent] = [...(eventsByNode[e.agent] ?? []), e];

  const nodeStatus = { ...s.nodeStatus };
  if (e.agent) {
    const ns = nodeStatusFromEvent(e);
    if (ns) nodeStatus[e.agent] = ns;
  }
  const runStatus =
    e.type === "status" && e.data?.kind === "status" ? e.data.status : s.runStatus;

  return { runStatus, logs, eventsByNode, nodeStatus };
}
