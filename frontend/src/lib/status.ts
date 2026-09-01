import type { NodeStatus, RunStatus } from "@/api";
import type { Tone } from "./tone.ts";

const RUN_TONE: Record<RunStatus, Tone> = {
  pending: "muted",
  running: "amber",
  succeeded: "low",
  failed: "crit",
  interrupted: "high",
};

const RUN_LABEL: Record<RunStatus, string> = {
  pending: "pending",
  running: "running",
  succeeded: "succeeded",
  failed: "failed",
  interrupted: "interrupted",
};

const RUN_ICON: Record<RunStatus, string> = {
  pending: "○",
  running: "◉",
  succeeded: "●",
  failed: "✕",
  interrupted: "■",
};

export function runTone(s: RunStatus): Tone {
  return RUN_TONE[s];
}
export function runLabel(s: RunStatus): string {
  return RUN_LABEL[s];
}
export function runIcon(s: RunStatus): string {
  return RUN_ICON[s];
}

const NODE_TONE: Record<NodeStatus, Tone> = {
  pending: "dim",
  running: "amber",
  completed: "low",
  error: "crit",
};
const NODE_ICON: Record<NodeStatus, string> = {
  pending: "○",
  running: "◉",
  completed: "●",
  error: "⊘",
};

export function nodeTone(s: NodeStatus): Tone {
  return NODE_TONE[s];
}
export function nodeIcon(s: NodeStatus): string {
  return NODE_ICON[s];
}

export const RUN_STATUS_ORDER: RunStatus[] = ["running", "pending", "succeeded", "interrupted", "failed"];
