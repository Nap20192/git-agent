/**
 * Interactive run graph. Pannable surface (drag empty space) with draggable,
 * selectable nodes. Layout is client-owned: initial positions come from the
 * node's x/y percent hints; the user can drag nodes and positions persist to
 * localStorage keyed by the node-id set. Sized for today's 3-node pipeline but
 * scales unchanged to sub-agent fan-out.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { GraphEdge, GraphNode } from "@/api";
import { nodeIcon, nodeTone } from "@/lib/status.ts";
import { toneVar } from "@/lib/tone.ts";
import styles from "./GraphCanvas.module.css";

interface Pos {
  x: number;
  y: number;
}
type Layout = Record<string, Pos>;

export interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** Per-node event counts for the corner badge. */
  eventCounts?: Record<string, number>;
}

// v2: coords are now percent [0..100] (were pixel-ish) — invalidate old layouts
const LS_KEY = "git-agent:graph-layout:v2:";

function initialLayout(nodes: GraphNode[]): Layout {
  const key = LS_KEY + nodes.map((n) => n.id).sort().join(",");
  try {
    const saved = localStorage.getItem(key);
    if (saved) return JSON.parse(saved) as Layout;
  } catch {
    /* ignore */
  }
  const l: Layout = {};
  nodes.forEach((n, i) => {
    l[n.id] = { x: n.x ?? 50, y: n.y ?? (i / Math.max(1, nodes.length - 1)) * 90 + 5 };
  });
  return l;
}

export function GraphCanvas({ nodes, edges, selectedId, onSelect, eventCounts }: GraphCanvasProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [layout, setLayout] = useState<Layout>(() => initialLayout(nodes));
  const [pan, setPan] = useState<Pos>({ x: 0, y: 0 });
  const drag = useRef<{ mode: "pan" | "node"; id?: string; startX: number; startY: number; origin: Pos; moved: boolean } | null>(null);

  // Re-seed layout when the node set changes (different run).
  useEffect(() => {
    setLayout(initialLayout(nodes));
    setPan({ x: 0, y: 0 });
  }, [nodes]);

  const persist = useCallback(
    (l: Layout) => {
      const key = LS_KEY + nodes.map((n) => n.id).sort().join(",");
      try {
        localStorage.setItem(key, JSON.stringify(l));
      } catch {
        /* ignore */
      }
    },
    [nodes],
  );

  const onPointerDownCanvas = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { mode: "pan", startX: e.clientX, startY: e.clientY, origin: pan, moved: false };
  };

  const onPointerDownNode = (e: React.PointerEvent, id: string) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { mode: "node", id, startX: e.clientX, startY: e.clientY, origin: layout[id], moved: false };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) d.moved = true;
    if (d.mode === "pan") {
      setPan({ x: d.origin.x + dx, y: d.origin.y + dy });
    } else if (d.id) {
      const rect = wrapRef.current?.getBoundingClientRect();
      if (!rect) return;
      const nx = Math.max(4, Math.min(96, d.origin.x + (dx / rect.width) * 100));
      const ny = Math.max(4, Math.min(96, d.origin.y + (dy / rect.height) * 100));
      setLayout((l) => ({ ...l, [d.id!]: { x: nx, y: ny } }));
    }
  };

  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.mode === "node" && d.id) {
      if (!d.moved) onSelect(d.id === selectedId ? null : d.id);
      else setLayout((l) => {
        persist(l);
        return l;
      });
    } else if (d.mode === "pan" && !d.moved) {
      onSelect(null);
    }
  };

  const pos = (id: string): Pos => layout[id] ?? { x: 50, y: 50 };

  return (
    <div
      ref={wrapRef}
      className={styles.canvas}
      onPointerDown={onPointerDownCanvas}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      <div className={styles.world} style={{ transform: `translate(${pan.x}px, ${pan.y}px)` }}>
        <svg className={styles.edges} viewBox="0 0 100 100" preserveAspectRatio="none">
          <defs>
            <marker id="gc-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="var(--border)" />
            </marker>
          </defs>
          {edges.map((ed, i) => {
            const a = pos(ed.from);
            const b = pos(ed.to);
            const target = nodes.find((n) => n.id === ed.to);
            const live = target?.status === "running";
            const done = target?.status === "completed";
            const color = live ? "var(--amber)" : done ? "#3a4a32" : ed.conditional ? "#2a2420" : "#242220";
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={color}
                strokeWidth={live ? 1.4 : 1}
                strokeDasharray={live ? "4 4" : ed.conditional ? "2 3" : "0"}
                vectorEffect="non-scaling-stroke"
                markerEnd="url(#gc-arrow)"
                style={live ? { animation: "vk-dash .6s linear infinite" } : undefined}
              />
            );
          })}
        </svg>

        {nodes.map((n) => {
          const p = pos(n.id);
          const selected = n.id === selectedId;
          const tone = toneVar(nodeTone(n.status));
          const count = eventCounts?.[n.id];
          return (
            <div
              key={n.id}
              className={styles.node}
              style={{ left: `${p.x}%`, top: `${p.y}%` }}
              onPointerDown={(e) => onPointerDownNode(e, n.id)}
            >
              <div
                className={[styles.box, selected ? styles.selected : "", n.kind === "agent" ? styles.agent : ""].filter(Boolean).join(" ")}
                style={selected ? { borderColor: "var(--amber)", boxShadow: "0 0 0 1px var(--amber), 0 0 14px rgba(255,175,0,.18)" } : undefined}
              >
                <div className={styles.boxHead}>
                  <span style={{ color: tone, fontSize: 10, animation: n.status === "running" ? "vk-pulse 1.1s ease-in-out infinite" : "none" }}>
                    {nodeIcon(n.status)}
                  </span>
                  <span className={styles.label}>{n.label}</span>
                  {count != null && count > 0 && <span className={styles.count}>{count}</span>}
                </div>
                <div className={styles.kind}>
                  <span>{n.kind}</span>
                  <span style={{ color: tone }}>{n.status}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div className={styles.hint}>drag nodes · drag empty space to pan</div>
    </div>
  );
}
