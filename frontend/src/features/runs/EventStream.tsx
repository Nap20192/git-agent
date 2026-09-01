/** Full-width event stream, bound to the graph by node id. Node filter chips +
 *  live follow. Row source node highlights when a node is selected. */
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
          <div
            key={e.cursor}
            className={styles.logRow}
            style={{ background: e.agent && e.agent === selectedNodeId ? "var(--hover)" : "transparent" }}
          >
            <span className={styles.logTime}>{fmtTime(e.ts)}</span>
            <span className={styles.logAgent} style={{ color: e.agent ? colorOf.get(e.agent) : "var(--dim)" }}>
              {e.agent ?? "—"}
            </span>
            <span className={styles.logMsg} style={{ color: e.level === "error" ? "var(--crit)" : e.level === "warn" ? "var(--high)" : "var(--text)" }}>
              {e.message}
            </span>
          </div>
        ))}
        {shown.length === 0 && <div className={styles.streamEmpty}>no events</div>}
      </div>
    </div>
  );
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso.slice(11, 19) : d.toLocaleTimeString("en-GB");
}
