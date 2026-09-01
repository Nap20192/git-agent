/** Flat list view of the run's agents (lead + delegated sub-agents), an
 *  alternative to the graph canvas. Clicking a row selects it — same selection
 *  that drives the NodeInspector. Sub-agents are indented under the lead. */
import type { GraphNode } from "@/api";
import { nodeIcon, nodeTone } from "@/lib/status.ts";
import { toneVar } from "@/lib/tone.ts";
import styles from "./agent-list.module.css";

interface Props {
  nodes: GraphNode[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  eventCounts?: Record<string, number>;
}

function meta(n: GraphNode): string {
  const bits: string[] = [];
  if (n.subagentType) bits.push(n.subagentType);
  if (n.toolCalls != null) bits.push(`${n.toolCalls} tools`);
  if (n.findings != null && n.findings > 0) bits.push(`${n.findings} findings`);
  if (n.tokenUsage) bits.push(`${n.tokenUsage.totalTokens.toLocaleString()} tok`);
  if (n.stopReason) bits.push(n.stopReason);
  return bits.join(" · ");
}

export function AgentList({ nodes, selectedId, onSelect, eventCounts }: Props) {
  // лид(ы) первыми, затем их сабагенты; сабагенты с отступом
  const ordered = [...nodes].sort((a, b) => {
    const rank = (n: GraphNode) => (n.parentId ? 1 : 0);
    return rank(a) - rank(b);
  });
  if (ordered.length === 0) return <div className={styles.empty}>no agents yet</div>;
  return (
    <div className={styles.list}>
      {ordered.map((n) => {
        const tone = toneVar(nodeTone(n.status));
        const count = eventCounts?.[n.id];
        const selected = n.id === selectedId;
        return (
          <div
            key={n.id}
            className={[styles.row, selected ? styles.selected : "", n.parentId ? styles.child : ""].filter(Boolean).join(" ")}
            onClick={() => onSelect(selected ? null : n.id)}
          >
            <span className={styles.icon} style={{ color: tone }}>
              {nodeIcon(n.status)}
            </span>
            <span className={styles.label} title={n.label}>
              {n.parentId && <span className={styles.tree}>└ </span>}
              {n.label}
            </span>
            <span className={styles.meta}>{meta(n)}</span>
            {count != null && count > 0 && <span className={styles.count}>{count}</span>}
            <span className={styles.status} style={{ color: tone }}>
              {n.status}
            </span>
          </div>
        );
      })}
    </div>
  );
}
