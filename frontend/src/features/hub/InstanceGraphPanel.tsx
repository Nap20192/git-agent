/** Run graph of one ход (ticket 012): star «Лид → Сабагенты» fed by the
 *  activity SSE. Node = status (color/pulse), short task description,
 *  duration, Находки counter; click → drawer with the self-report. */
import { useEffect, useMemo, useState } from "react";
import type { ActivityEvent } from "@/api/hub";
import { Badge, Drawer, Panel, PanelHeader, StatusDot } from "@/components/primitives";
import { toneVar } from "@/lib/tone.ts";
import { duration, foldActivity, statusTone, type SubagentNode } from "./activity.ts";
import styles from "./hub.module.css";

const LEAD = { x: 22, y: 50 };

function taskXY(i: number, n: number): { x: number; y: number } {
  if (n <= 1) return { x: 72, y: 50 };
  return { x: 72, y: Math.max(10, Math.min(90, 50 + (i - (n - 1) / 2) * (80 / Math.max(1, n - 1)))) };
}

export function InstanceGraphPanel({
  frames,
  done,
  live,
  turnLabel,
  onBackToLive,
}: {
  frames: ActivityEvent[];
  /** Stream ended (replay finished or the ход closed). */
  done: boolean;
  /** Following the live/latest turn (no eventId pinned). */
  live: boolean;
  /** "live" or "Событие #N" — shown in the header. */
  turnLabel: string;
  onBackToLive?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<SubagentNode | null>(null);
  const graph = useMemo(() => foldActivity(frames), [frames]);
  const running = graph.started && !graph.finished && !done;

  // tick once a second while the ход runs so durations count up
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [running]);

  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setExpanded(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);

  const leadStatus = graph.failed
    ? ("failed" as const)
    : graph.finished
      ? ("done" as const)
      : graph.started
        ? ("working" as const)
        : ("queued" as const);

  const canvas = (
    <div className={styles.graphCanvas}>
      {!graph.started && frames.length === 0 && (
        <div className={styles.graphEmpty}>
          {done ? "Нет активности этого хода — Экземпляр ещё не работал." : "connecting…"}
        </div>
      )}
      <svg className={styles.graphEdges} viewBox="0 0 100 100" preserveAspectRatio="none">
        {graph.tasks.map((t, i) => {
          const p = taskXY(i, graph.tasks.length);
          const activeEdge = t.status === "working" || t.status === "queued";
          return (
            <line
              key={t.taskId}
              x1={LEAD.x}
              y1={LEAD.y}
              x2={p.x}
              y2={p.y}
              stroke={activeEdge ? "var(--amber)" : "var(--border)"}
              strokeWidth={activeEdge ? 1.4 : 1}
              strokeDasharray={activeEdge ? "4 4" : "0"}
              vectorEffect="non-scaling-stroke"
              style={activeEdge ? { animation: "vk-dash .6s linear infinite" } : undefined}
            />
          );
        })}
      </svg>

      {(graph.started || frames.length > 0) && (
        <div className={`${styles.graphNode} ${styles.graphLead}`} style={{ left: `${LEAD.x}%`, top: `${LEAD.y}%` }}>
          <div className={styles.graphNodeHead}>
            <StatusDot tone={statusTone(leadStatus)} pulse={leadStatus === "working"} />
            <span className={styles.graphNodeLabel}>Лид</span>
            {graph.leadFindings > 0 && <span className={styles.graphCount}>⚠ {graph.leadFindings}</span>}
          </div>
          <div className={styles.graphNodeMeta}>
            <span style={{ color: toneVar(statusTone(leadStatus)) }}>{leadStatus}</span>
            <span>{duration(graph.startedAt, graph.finishedAt) ?? "—"}</span>
          </div>
          {graph.error && <div className={styles.graphNodeError}>{graph.error}</div>}
        </div>
      )}

      {graph.tasks.map((t, i) => {
        const p = taskXY(i, graph.tasks.length);
        return (
          <div
            key={t.taskId}
            className={`${styles.graphNode} ${styles.graphTask}`}
            style={{ left: `${p.x}%`, top: `${p.y}%` }}
            onClick={() => setSelected(t)}
            title={t.description}
          >
            <div className={styles.graphNodeHead}>
              <StatusDot tone={statusTone(t.status)} pulse={t.status === "working"} />
              <span className={styles.graphNodeLabel}>{t.description || `subagent ${t.taskId.slice(-6)}`}</span>
              {t.findingsCount != null && t.findingsCount > 0 && (
                <span className={styles.graphCount}>⚠ {t.findingsCount}</span>
              )}
            </div>
            <div className={styles.graphNodeMeta}>
              <span style={{ color: toneVar(statusTone(t.status)) }}>{t.status}</span>
              <span>{duration(t.startedAt, t.finishedAt) ?? "—"}</span>
            </div>
          </div>
        );
      })}
    </div>
  );

  const header = (
    <PanelHeader
      icon="✧"
      title="GRAPH — ХОД"
      right={
        <span className={styles.graphHeadRight}>
          {live ? (
            <Badge tone={running ? "amber" : "muted"}>{running ? "live" : "последний ход"}</Badge>
          ) : (
            <>
              <Badge tone="blue">{turnLabel}</Badge>
              {onBackToLive && (
                <button type="button" className={styles.graphHeadBtn} onClick={onBackToLive}>
                  → live
                </button>
              )}
            </>
          )}
          <button
            type="button"
            className={styles.graphHeadBtn}
            onClick={() => setExpanded((e) => !e)}
            title={expanded ? "collapse" : "развернуть на весь экран"}
          >
            {expanded ? "✕" : "⛶"}
          </button>
        </span>
      }
    />
  );

  return (
    <>
      <Panel className={expanded ? styles.graphFullscreen : undefined}>
        {header}
        {canvas}
      </Panel>
      <Drawer
        open={selected != null}
        title={selected ? `Сабагент — ${selected.description ?? selected.taskId}` : ""}
        onClose={() => setSelected(null)}
      >
        {selected && (
          <div className={styles.graphDrawer}>
            <div className={styles.graphDrawerRow}>
              <StatusDot tone={statusTone(selected.status)} pulse={selected.status === "working"} />
              <span style={{ color: toneVar(statusTone(selected.status)) }}>{selected.status}</span>
              <span className={styles.graphDrawerMeta}>{duration(selected.startedAt, selected.finishedAt) ?? ""}</span>
              {selected.findingsCount != null && (
                <span className={styles.graphDrawerMeta}>Находок: {selected.findingsCount}</span>
              )}
            </div>
            {selected.error && <p className={styles.error}>{selected.error}</p>}
            <div className={styles.graphReport}>
              {selected.report ?? (selected.status === "working" || selected.status === "queued"
                ? "Сабагент ещё работает — самоотчёт появится по завершении."
                : "Самоотчёт не получен.")}
            </div>
          </div>
        )}
      </Drawer>
    </>
  );
}
