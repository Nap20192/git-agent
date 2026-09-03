/** Run graph of one ход (ticket 012): star «Лид → Сабагенты» fed by the
 *  activity SSE. Node = status glyph, task description, duration, Находки
 *  counter; click → drawer with the self-report. Renders as the graph tab. */
import { useEffect, useMemo, useState } from "react";
import type { ActivityEvent, ActivityStatus } from "@/api/hub";
import { duration, foldActivity, type SubagentNode } from "./activity.ts";
import { Drawer } from "./ui.tsx";

const LEAD = { x: 22, y: 50 };
const taskXY = (i: number, n: number) => (n <= 1 ? { x: 72, y: 50 } : { x: 72, y: Math.max(10, Math.min(90, 50 + (i - (n - 1) / 2) * (80 / Math.max(1, n - 1)))) });

export const STATUS_GLYPH: Record<ActivityStatus, string> = { queued: "○", working: "●", done: "✓", failed: "✗", timeout: "✗" };
export const STATUS_COLOR: Record<ActivityStatus, string> = {
  queued: "var(--text-comment)",
  working: "var(--accent)",
  done: "var(--text-muted)",
  failed: "var(--error)",
  timeout: "var(--warning)",
};
export function Status({ s }: { s: ActivityStatus }) {
  return (
    <span style={{ color: STATUS_COLOR[s] }} className={s === "working" ? "pulse" : ""}>
      {STATUS_GLYPH[s]}
    </span>
  );
}

export function InstanceGraphPanel({ frames, done, live, turnLabel, onBackToLive }: { frames: ActivityEvent[]; done: boolean; live: boolean; turnLabel: string; onBackToLive?: () => void }) {
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

  const leadStatus: ActivityStatus = graph.failed ? "failed" : graph.finished ? "done" : graph.started ? "working" : "queued";

  return (
    <div className="graph">
      <div className="graph-head">
        {live ? (
          <span>{running ? <span className="accent pulse">● live</span> : "last turn"}</span>
        ) : (
          <>
            <span className="accent">{turnLabel}</span>
            {onBackToLive && <button className="btn xs" onClick={onBackToLive}>→ live</button>}
          </>
        )}
      </div>
      {!graph.started && frames.length === 0 && (
        <div className="empty" style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
          {done ? "no activity for this turn — the instance has not worked yet." : "connecting…"}
        </div>
      )}
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        {graph.tasks.map((t, i) => {
          const p = taskXY(i, graph.tasks.length);
          const active = t.status === "working" || t.status === "queued";
          return (
            <line
              key={t.taskId}
              x1={LEAD.x} y1={LEAD.y} x2={p.x} y2={p.y}
              stroke={active ? "var(--accent)" : "var(--border)"}
              strokeWidth={active ? 1.4 : 1}
              strokeDasharray={active ? "4 4" : "0"}
              vectorEffect="non-scaling-stroke"
              style={active ? { animation: "vk-dash .6s linear infinite" } : undefined}
            />
          );
        })}
      </svg>
      {(graph.started || frames.length > 0) && (
        <div className="gnode lead" style={{ left: `${LEAD.x}%`, top: `${LEAD.y}%` }}>
          <div className="name"><Status s={leadStatus} /> lead{graph.leadFindings > 0 && <span className="muted"> · {graph.leadFindings} findings</span>}</div>
          <div className="meta"><span style={{ color: STATUS_COLOR[leadStatus] }}>{leadStatus}</span><span>{duration(graph.startedAt, graph.finishedAt) ?? "—"}</span></div>
          {graph.error && <div className="err small">{graph.error}</div>}
        </div>
      )}
      {graph.tasks.map((t, i) => {
        const p = taskXY(i, graph.tasks.length);
        return (
          <div key={t.taskId} className="gnode task" style={{ left: `${p.x}%`, top: `${p.y}%` }} onClick={() => setSelected(t)} title={t.description}>
            <div className="name"><Status s={t.status} /> {t.description || `subagent ${t.taskId.slice(-6)}`}</div>
            <div className="meta">
              <span style={{ color: STATUS_COLOR[t.status] }}>{t.status}{t.findingsCount ? ` · ${t.findingsCount} findings` : ""}</span>
              <span>{duration(t.startedAt, t.finishedAt) ?? "—"}</span>
            </div>
          </div>
        );
      })}
      <Drawer open={selected != null} title={`subagent · ${selected?.taskId.slice(-6) ?? ""}`} onClose={() => setSelected(null)}>
        {selected && <SubagentDetail t={selected} />}
      </Drawer>
    </div>
  );
}

export function SubagentDetail({ t }: { t: SubagentNode }) {
  return (
    <>
      <div className="pretty">{t.description ?? t.taskId}</div>
      <div className="small muted">
        <Status s={t.status} /> <span style={{ color: STATUS_COLOR[t.status] }}>{t.status}</span> · {duration(t.startedAt, t.finishedAt) ?? "—"}
        {t.findingsCount != null && ` · ${t.findingsCount} findings`}
      </div>
      {t.error && <div className="err small">{t.error}</div>}
      <div className="small comment" style={{ whiteSpace: "pre-wrap" }}>
        {t.report ?? (t.status === "working" || t.status === "queued" ? "still working — the self-report lands when it finishes." : "no self-report received.")}
      </div>
    </>
  );
}
