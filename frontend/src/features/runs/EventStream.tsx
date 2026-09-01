/** Full-width event stream, bound to the graph by node id. Node filter chips +
 *  live follow. Renders the full event payload: agent reasoning text, tool calls
 *  with args, tool results, and lifecycle — not just the (often empty) message. */
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphNode, RunEvent } from "@/api";
import { PanelHeader } from "@/components/primitives";
import styles from "./run.module.css";

const AGENT_COLORS = ["var(--amber)", "var(--blue)", "var(--low)", "var(--high)", "var(--med)"];

export interface EventStreamProps {
  logs: RunEvent[];
  nodes: GraphNode[];
  selectedNodeId: string | null;
  live: boolean;
}

export function EventStream({ logs, nodes, selectedNodeId, live }: EventStreamProps) {
  const [filter, setFilter] = useState<string>("all");
  const [follow, setFollow] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const colorOf = useMemo(() => {
    const m = new Map<string, string>();
    nodes.forEach((n, i) => m.set(n.id, AGENT_COLORS[i % AGENT_COLORS.length]));
    return m;
  }, [nodes]);

  const shown = filter === "all" ? logs : logs.filter((l) => l.agent === filter);

  useEffect(() => {
    if (follow && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [shown.length, follow]);

  return (
    <div className={styles.streamPane}>
      <PanelHeader
        icon="$_"
        title="EVENT STREAM"
        right={
          <div className={styles.streamTools}>
            <span
              className={[styles.chip, filter === "all" ? styles.chipOn : ""].join(" ")}
              onClick={() => setFilter("all")}
            >
              all
            </span>
            {nodes.map((n) => (
              <span
                key={n.id}
                className={[styles.chip, filter === n.id ? styles.chipOn : ""].join(" ")}
                style={{ color: filter === n.id ? colorOf.get(n.id) : undefined }}
                onClick={() => setFilter(n.id)}
              >
                {n.label}
              </span>
            ))}
            {live && (
              <span
                className={[styles.follow, follow ? styles.followOn : ""].join(" ")}
                onClick={() => setFollow((f) => !f)}
              >
                ● live
              </span>
            )}
          </div>
        }
      />
      <div
        ref={scrollRef}
        className={styles.streamBody}
        onWheel={() => follow && setFollow(false)}
      >
        {shown.map((e) => (
          <EventRow
            key={e.cursor}
            e={e}
            color={e.agent ? colorOf.get(e.agent) ?? "var(--dim)" : "var(--dim)"}
            highlight={!!e.agent && e.agent === selectedNodeId}
          />
        ))}
        {shown.length === 0 && <div className={styles.streamEmpty}>no events</div>}
      </div>
    </div>
  );
}

function EventRow({ e, color, highlight }: { e: RunEvent; color: string; highlight: boolean }) {
  const parts = describe(e);
  return (
    <div
      className={styles.logRow}
      style={{ background: highlight ? "var(--hover)" : "transparent" }}
    >
      <span className={styles.logTime}>{fmtTime(e.ts)}</span>
      <span className={styles.logAgent} style={{ color }} title={e.agent ?? ""}>
        {e.agent ?? "—"}
      </span>
      <div className={styles.logBody}>
        {parts.map((p, i) => (
          <Line key={i} p={p} />
        ))}
      </div>
    </div>
  );
}

/** Tool calls / results clamp to 3 lines and expand on click; text lines render as-is. */
function Line({ p }: { p: Part }) {
  const clampable = p.cls === "logTool" || p.cls === "logResult";
  const [expanded, setExpanded] = useState(false);
  const cls = [styles[p.cls], clampable && !expanded ? styles.clamp3 : ""].filter(Boolean).join(" ");
  return (
    <div
      className={cls}
      style={{ ...(p.color ? { color: p.color } : {}), ...(clampable ? { cursor: "pointer" } : {}) }}
      onClick={clampable ? () => setExpanded((v) => !v) : undefined}
      title={clampable && !expanded ? "click to expand" : undefined}
    >
      {p.text}
    </div>
  );
}

type Part = { cls: "logMsg" | "logThink" | "logTool" | "logResult" | "logLifecycle"; text: string; color?: string };

/** Turn a RunEvent into displayable lines — reasoning, tool calls, results, lifecycle. */
function describe(e: RunEvent): Part[] {
  const d = e.data;
  if (d && "kind" in d) {
    switch (d.kind) {
      case "task_started":
        return [{ cls: "logLifecycle", text: `▶ delegate ${d.subagentType} — ${d.description}`, color: "var(--blue)" }];
      case "task_step": {
        const out: Part[] = [];
        if (d.text?.trim()) {
          out.push(
            d.frameKind === "tool"
              ? { cls: "logResult", text: `${d.toolName ? d.toolName + " ▸ " : ""}${d.text}` }
              : { cls: "logThink", text: d.text },
          );
        }
        for (const c of d.toolCalls ?? []) {
          out.push({ cls: "logTool", text: `⚙ ${c.name}(${c.args})`, color: "var(--amber)" });
        }
        return out.length ? out : [{ cls: "logMsg", text: e.message ?? "" }];
      }
      case "task_terminal": {
        const err = d.error ? ` — ${d.error}` : "";
        const tok = d.usage ? ` · ${d.usage.totalTokens.toLocaleString()} tok` : "";
        return [{ cls: "logLifecycle", text: `■ ${d.status}${err}${tok}`, color: termColor(d.status) }];
      }
      case "agent_step": {
        const out: Part[] = [];
        if (d.text?.trim()) out.push({ cls: "logThink", text: d.text });
        for (const c of d.toolCalls ?? []) {
          out.push({ cls: "logTool", text: `⚙ ${c.name}(${c.args})`, color: "var(--amber)" });
        }
        for (const r of d.toolResults ?? []) {
          out.push({ cls: "logResult", text: r });
        }
        return out.length ? out : [{ cls: "logMsg", text: e.message ?? "" }];
      }
      case "node_status":
        return [{ cls: "logLifecycle", text: `● ${d.node} ${d.status}`, color: "var(--low)" }];
      case "status":
        return [{ cls: "logLifecycle", text: `run ${d.status}`, color: "var(--low)" }];
    }
  }
  if (e.message?.trim()) {
    const color = e.level === "error" ? "var(--crit)" : e.level === "warn" ? "var(--high)" : undefined;
    return [{ cls: "logMsg", text: e.message, color }];
  }
  // last resort: show raw payload so nothing is ever silently dropped
  return [{ cls: "logMsg", text: e.data ? JSON.stringify(e.data) : e.type, color: "var(--dim)" }];
}

function termColor(status: string): string {
  return status === "completed" ? "var(--low)" : "var(--crit)";
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso.slice(11, 19) : d.toLocaleTimeString("en-GB");
}
