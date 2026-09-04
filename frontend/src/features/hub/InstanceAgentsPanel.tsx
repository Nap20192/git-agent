/** Agents tab of the Playground: the lead (the agent itself) plus one row per
 *  Сабагент of the ход, fed by the activity SSE. Selecting a row opens its
 *  work: task, status, self-report / Отчёт as markdown with important bits
 *  highlighted, long text clamped, and the work log (tool_call / tool_result /
 *  text frames) once the runner emits it. */
import type { ReactNode } from "react";
import type { ActivityStatus, Report } from "@/api/hub";
import { combinedWork, duration, fmtTokens, type AgentNode, type Tokens, type TurnGraph, type WorkFrame } from "./activity.ts";
import { Clamp, Rich } from "./rich.tsx";
import { ReportView } from "./findings.tsx";
import { Panel } from "./ui.tsx";

const COLS = "2ch 1fr 80px 70px 80px 70px";
const GLYPH: Record<ActivityStatus, string> = { queued: "○", working: "●", done: "✓", failed: "✗", timeout: "✗" };
export const STATUS_COLOR: Record<ActivityStatus, string> = {
  queued: "var(--text-comment)",
  working: "var(--accent)",
  done: "var(--text-muted)",
  failed: "var(--error)",
  timeout: "var(--warning)",
};

export function Status({ s }: { s: ActivityStatus }) {
  return <span style={{ color: STATUS_COLOR[s] }} className={s === "working" ? "pulse" : ""}>{GLYPH[s]}</span>;
}

export function InstanceAgentsPanel({ graph, leadName, report, selected, onSelect, footer }: {
  graph: TurnGraph;
  leadName: string;
  /** Отчёт of the shown ход (pinned event or latest) — the lead's body. */
  report?: Report;
  selected: string | null;
  onSelect: (id: string | null) => void;
  footer: ReactNode;
}) {
  const lead: AgentNode = {
    taskId: "lead",
    description: `lead · ${leadName}`,
    status: graph.failed ? "failed" : graph.finished ? "done" : graph.started ? "working" : "queued",
    startedAt: graph.startedAt,
    finishedAt: graph.finishedAt,
    findingsCount: graph.leadFindings,
    error: graph.error,
    report: report?.summary,
    reportObj: report,
    work: graph.leadWork,
    tokens: graph.leadTokens,
  };
  // combined feed: every agent's work in one chronological log, lines labelled by who did it
  const all: AgentNode = {
    taskId: "all",
    description: "all agents · combined feed",
    status: lead.status,
    startedAt: graph.startedAt,
    finishedAt: graph.finishedAt,
    findingsCount: graph.leadFindings + graph.tasks.reduce((n, t) => n + (t.findingsCount ?? 0), 0),
    work: combinedWork(graph),
    tokens: graph.tokens,
  };
  const rows = [all, lead, ...graph.tasks];
  const cur = rows.find((a) => a.taskId === selected) ?? rows.find((a) => a.status === "working" && a.taskId !== "all") ?? lead;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr minmax(380px, 45%)", gap: 16, flex: 1, minHeight: 0 }}>
      <div className="box" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div className="thead" style={{ "--cols": COLS } as React.CSSProperties}>
          <span></span><span>agent</span><span>status</span><span>time</span><span>tokens</span><span>findings</span>
        </div>
        <div style={{ overflow: "auto", flex: 1 }}>
          {rows.map((a, i) => (
            <div key={a.taskId} className={`trow click${a.taskId === cur.taskId ? " sel" : ""}`} style={{ "--cols": COLS, padding: "8px 12px" } as React.CSSProperties} onClick={() => onSelect(a.taskId)}>
              <Status s={a.status} />
              <span className={`ellip${i <= 1 ? "" : " comment"}`} style={i <= 1 ? { fontWeight: 700 } : { paddingLeft: "2ch" }}>{a.description ?? a.taskId}</span>
              <span style={{ color: STATUS_COLOR[a.status] }}>{a.status}</span>
              <span className="small muted">{duration(a.startedAt, a.finishedAt) ?? "—"}</span>
              <span className="small muted" title={tokensTitle(a.tokens)}>{tokensText(a.tokens)}</span>
              <span className="small muted">{a.findingsCount || "—"}</span>
            </div>
          ))}
          {!graph.started && graph.tasks.length === 0 && <div className="empty">no activity for this turn yet — trigger a run; the lead fans out per build limits.</div>}
        </div>
        <div className="small muted" style={{ padding: "6px 12px", borderTop: "1px solid var(--border)" }}>{footer}</div>
      </div>
      <Panel label={cur.taskId === "all" ? "all agents" : cur.taskId === "lead" ? "lead" : `subagent · ${cur.taskId.slice(-6)}`} dim={cur.status} className="elev col">
        <div style={{ padding: "20px 12px 12px", display: "flex", flexDirection: "column", gap: 10, overflow: "auto" }}>
          <AgentDetail a={cur} />
        </div>
      </Panel>
    </div>
  );
}

const tokensText = (t: Tokens) => (t.input || t.output ? fmtTokens(t.input + t.output) : "—");
const tokensTitle = (t: Tokens) => `${t.input.toLocaleString()} in · ${t.output.toLocaleString()} out`;

function AgentDetail({ a }: { a: AgentNode }) {
  const idle = a.status === "working" || a.status === "queued";
  const combined = a.taskId === "all";
  return (
    <>
      <div className="pretty" style={{ fontWeight: 700 }}>{a.description ?? a.taskId}</div>
      <div className="small muted">
        <Status s={a.status} /> <span style={{ color: STATUS_COLOR[a.status] }}>{a.status}</span> · {duration(a.startedAt, a.finishedAt) ?? "—"}
        {a.findingsCount ? ` · ${a.findingsCount} findings` : ""}
        {(a.tokens.input || a.tokens.output) ? <> · <span title="LLM tokens: prompt in · completion out">{fmtTokens(a.tokens.input + a.tokens.output)} tokens ({fmtTokens(a.tokens.input)} in · {fmtTokens(a.tokens.output)} out)</span></> : ""}
      </div>
      {a.error && <div className="err small pretty">{a.error}</div>}
      {!combined && <section>
        <div className="flabel" style={{ marginBottom: 4 }}>{a.taskId === "lead" ? "report" : "self-report"}</div>
        {a.reportObj ? <Clamp><ReportView report={a.reportObj} /></Clamp> : a.report ? <Clamp><Rich>{a.report}</Rich></Clamp> : <div className="small muted">{idle ? "still working — the report lands when it finishes." : "no report received."}</div>}
      </section>}
      <section>
        <div className="flabel" style={{ marginBottom: 4 }}>{combined ? "combined feed" : "work log"} · {a.work.length}</div>
        {a.work.length === 0 && <div className="small muted">{idle ? "waiting for work frames…" : "no work frames for this turn."}</div>}
        {a.work.map((w, i) => <WorkLine key={i} w={w} />)}
      </section>
    </>
  );
}

/** "340ms" / "2.1s" / "1m 05s". */
const fmtMs = (ms: number) => (ms < 1000 ? `${ms}ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.floor(ms / 60_000)}m ${String(Math.round((ms % 60_000) / 1000)).padStart(2, "0")}s`);

function WorkLine({ w }: { w: WorkFrame }) {
  const who = w.who && <span className="comment ellip" title={w.who} style={{ fontSize: 11 }}>{w.who === "lead" ? <b>lead</b> : w.who}</span>;
  if (w.kind === "text") {
    if (!w.text) return null;
    return who ? (
      <div className="small" style={{ display: "grid", gridTemplateColumns: "14ch 1fr", gap: 6, padding: "3px 0", borderBottom: "1px solid var(--border)" }}>
        {who}<Clamp lines={6}><Rich>{w.text}</Rich></Clamp>
      </div>
    ) : <Clamp lines={6}><Rich>{w.text}</Rich></Clamp>;
  }
  const call = w.kind === "tool_call";
  return (
    <div className="small" style={{ display: "grid", gridTemplateColumns: who ? "14ch 2ch 1fr auto" : "2ch 1fr auto", gap: 4, padding: "3px 0", borderBottom: "1px solid var(--border)" }}>
      {who}
      <span className={call ? "accent" : "muted"}>{call ? "⚙" : "↳"}</span>
      <Clamp lines={3}><span className={call ? "" : "comment"} style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{w.text}</span></Clamp>
      {call && <span className="muted" title="how long the tool ran (call → result)">{w.durationMs === undefined ? "…" : fmtMs(w.durationMs)}</span>}
    </div>
  );
}
