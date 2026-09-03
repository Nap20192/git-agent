/** Activity feed of one ход (ticket 012): SSE hook + frame folding into the
 *  agents list «Лид + Сабагенты» and the activity log. */
import { useEffect, useState } from "react";
import { useHubApi, type ActivityEvent, type ActivityStatus } from "@/api/hub";

const LIVE_RECONNECT_MS = 4000;

/**
 * Subscribes to the activity stream of an Экземпляр. eventId null follows the
 * live/latest turn and re-subscribes after `done` so the next ход shows up on
 * its own; a concrete eventId is a one-shot replay of that turn.
 */
export function useInstanceActivity(instanceId: number, eventId: number | null) {
  const api = useHubApi();
  const [frames, setFrames] = useState<ActivityEvent[]>([]);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!Number.isFinite(instanceId)) return;
    let cancelled = false;
    let timer: number | undefined;
    const ctl = new AbortController();

    const run = async () => {
      const batch: ActivityEvent[] = [];
      let ended = false;
      try {
        await api.activity(
          instanceId,
          eventId,
          (e) => {
            if (cancelled) return;
            if (e.kind === "done") {
              ended = true;
              return;
            }
            batch.push(e);
            setFrames([...batch]);
            setDone(false);
          },
          ctl.signal,
        );
      } catch {
        /* aborted / network hiccup — reconnect below if following live */
      }
      if (cancelled) return;
      setDone(ended);
      if (eventId == null) timer = window.setTimeout(run, LIVE_RECONNECT_MS);
    };

    setFrames([]);
    setDone(false);
    run();
    return () => {
      cancelled = true;
      ctl.abort();
      if (timer != null) window.clearTimeout(timer);
    };
  }, [api, instanceId, eventId]);

  return { frames, done };
}

export interface WorkFrame {
  kind: "tool_call" | "tool_result" | "text";
  text: string;
  ts?: string;
}

export interface AgentNode {
  taskId: string;
  description?: string;
  status: ActivityStatus;
  startedAt?: string;
  finishedAt?: string;
  findingsCount?: number;
  /** Terminal error (timeout/failure reason). */
  error?: string;
  /** Self-report text from the task_report frame. */
  report?: string;
  /** The lead's Отчёт object (structured when the agent wrote one). */
  reportObj?: import("@/api/hub").Report;
  /** Work log (tool_call / tool_result / text frames), oldest first. */
  work: WorkFrame[];
}
/** @deprecated alias — the star graph is gone, rows are AgentNode now. */
export type SubagentNode = AgentNode;

export interface TurnGraph {
  started: boolean;
  finished: boolean;
  failed: boolean;
  /** Накопленные Находки Лида (last node/run frame wins). */
  leadFindings: number;
  startedAt?: string;
  finishedAt?: string;
  error?: string;
  tasks: AgentNode[];
  /** The lead's own work log (frames without taskId). */
  leadWork: WorkFrame[];
}

/** Folds the frame stream into the star: lead state + one node per Сабагент. */
export function foldActivity(frames: ActivityEvent[]): TurnGraph {
  const graph: TurnGraph = {
    started: false,
    finished: false,
    failed: false,
    leadFindings: 0,
    tasks: [],
    leadWork: [],
  };
  const byId = new Map<string, AgentNode>();
  const node = (taskId: string): AgentNode => {
    let task = byId.get(taskId);
    if (!task) {
      task = { taskId, status: "queued", work: [] };
      byId.set(taskId, task);
      graph.tasks.push(task);
    }
    return task;
  };
  for (const f of frames) {
    if (f.findingsCount != null && f.kind !== "task_finished" && f.kind !== "task_failed") {
      graph.leadFindings = f.findingsCount;
    }
    switch (f.kind) {
      case "run_started":
        graph.started = true;
        graph.startedAt = f.ts ?? undefined;
        break;
      case "run_finished":
        graph.finished = true;
        graph.finishedAt = f.ts ?? undefined;
        break;
      case "run_failed":
        graph.finished = true;
        graph.failed = true;
        graph.finishedAt = f.ts ?? undefined;
        graph.error = f.description ?? undefined;
        break;
      case "task_started":
      case "task_finished":
      case "task_failed":
      case "task_report": {
        if (!f.taskId) break;
        const task = node(f.taskId);
        if (f.kind === "task_report") {
          task.report = f.description ?? undefined;
          break;
        }
        if (f.status) task.status = f.status;
        if (f.description && f.kind === "task_started") task.description = f.description;
        if (f.kind === "task_started" && !task.startedAt) task.startedAt = f.ts ?? undefined;
        if (f.kind !== "task_started") {
          task.finishedAt = f.ts ?? undefined;
          if (f.findingsCount != null) task.findingsCount = f.findingsCount;
          if (f.description) task.error = f.description;
        }
        break;
      }
      case "tool_call":
      case "tool_result":
      case "text": {
        const w: WorkFrame = { kind: f.kind as WorkFrame["kind"], text: f.description ?? "", ts: f.ts ?? undefined };
        (f.taskId ? node(f.taskId).work : graph.leadWork).push(w);
        break;
      }
      default:
        break;
    }
  }
  return graph;
}

/** Human line for the activity log; null = frame carries nothing worth a line. */
export function activityLine(f: ActivityEvent): string | null {
  const task = f.taskId ? `subagent ${f.taskId.slice(-6)}` : "";
  switch (f.kind) {
    case "run_started":
      return "turn started";
    case "run_finished":
      return `turn finished — findings: ${f.findingsCount ?? 0}`;
    case "run_failed":
      return `turn failed — ${f.description ?? "error"}`;
    case "node":
      return `node ${f.description ?? "?"} ✓`;
    case "tool_call":
      return `${task || "lead"} ⚙ ${(f.description ?? "").slice(0, 80)}`;
    case "task_started":
      return f.status === "queued"
        ? `${task} queued — ${f.description ?? ""}`.trim()
        : `${task} working`;
    case "task_finished":
      return `${task} done${f.findingsCount ? ` — findings: ${f.findingsCount}` : ""}`;
    case "task_failed":
      return `${task} ${f.status ?? "failed"}${f.description ? ` — ${f.description}` : ""}`;
    default:
      return null;
  }
}

/** "1m 23s" between two ISO stamps (end defaults to now for live nodes). */
export function duration(startedAt?: string, finishedAt?: string): string | null {
  if (!startedAt) return null;
  const ms = (finishedAt ? new Date(finishedAt).getTime() : Date.now()) - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  const s = Math.floor(ms / 1000);
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}
