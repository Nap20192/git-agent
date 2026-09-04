/** Находки v2 + structured Отчёт. FindingsTable — sortable table with expandable
 *  rows (description / impact / evidence / remediation / references / blame);
 *  FindingsPanel — filters (severity, category, introduced by, event) over a
 *  server-side list + export csv / copy markdown through the hub export
 *  endpoint. ReportView — the structured report (scope, severity summary, top
 *  risks, recommendations, limitations) with the summary markdown as fallback. */
import { useState } from "react";
import type { Finding, FindingExportFormat, FindingFilters, IntroducedBy, RepoEvent, Report } from "@/api/hub";
import { useAsync } from "@/hooks";
import { Clamp, Rich } from "./rich.tsx";
import { ago, sha, useShell } from "./ui.tsx";

const COLS = "72px 1.6fr 100px 1.2fr 1.5fr 90px 76px";
const SEV_ORDER = ["critical", "crit", "high", "medium", "med", "low", "info"];
const SEV_COLOR: Record<string, string> = { critical: "var(--error)", crit: "var(--error)", high: "var(--error)", medium: "var(--warning)", med: "var(--warning)", low: "var(--text-muted)", info: "var(--text-comment)" };
export const sevColor = (s: string) => SEV_COLOR[s.toLowerCase()] ?? "var(--text)";
const sevRank = (s: string) => { const i = SEV_ORDER.indexOf(s.toLowerCase()); return i < 0 ? SEV_ORDER.length : i; };
/** critical → info, then newest first. */
export const bySeverity = (a: Finding, b: Finding) => sevRank(a.severity) - sevRank(b.severity) || (b.createdAt ?? "").localeCompare(a.createdAt ?? "");

const loc = (f: Finding) => (f.file ? `${f.file}${f.lineStart != null ? `:${f.lineStart}${f.lineEnd != null && f.lineEnd !== f.lineStart ? `-${f.lineEnd}` : ""}` : ""}` : "—");

function Introduced({ f }: { f: Finding }) {
  const who = f.blameAuthor ? <span title={f.blameEmail ?? undefined}>{f.blameAuthor}</span> : null;
  return (
    <span className="ellip" title={f.blameCommitMessage ?? undefined}>
      {who}
      {f.blameDate && <span className="muted"> @ {ago(f.blameDate)}</span>}
      {f.blameCommit && <span className="comment"> · {sha(f.blameCommit)}</span>}
      {f.introducedBy === "this_event" && <span className="tag">this event</span>}
      {f.introducedBy === "earlier" && <span className="tag dim">earlier</span>}
      {!who && !f.blameCommit && !f.introducedBy && "—"}
    </span>
  );
}

function Detail({ f }: { f: Finding }) {
  const block = (label: string, body?: string | null) => body ? (
    <section>
      <div className="flabel" style={{ marginBottom: 4 }}>{label}</div>
      <Clamp lines={8}><Rich>{body}</Rich></Clamp>
    </section>
  ) : null;
  return (
    <div className="fdetail">
      {block("description", f.description)}
      {block("impact", f.impact)}
      {f.evidence && (
        <section>
          <div className="flabel" style={{ marginBottom: 4 }}>evidence{f.file ? ` · ${loc(f)}` : ""}</div>
          <pre className="code">{f.evidence}</pre>
        </section>
      )}
      {block("remediation", f.remediation)}
      {(f.blameCommit || f.blameAuthor) && (
        <section>
          <div className="flabel" style={{ marginBottom: 4 }}>introduced by</div>
          <div className="small comment">
            {f.blameAuthor}{f.blameEmail ? ` <${f.blameEmail}>` : ""}{f.blameCommit ? ` · ${f.blameCommit}` : ""}{f.blameDate ? ` · ${new Date(f.blameDate).toLocaleString()}` : ""}
            {f.blameCommitMessage && <div>“{f.blameCommitMessage}”</div>}
          </div>
        </section>
      )}
      {!!f.references?.length && (
        <section>
          <div className="flabel" style={{ marginBottom: 4 }}>references</div>
          {f.references.map((r) => (
            <div key={r} className="small"><a href={r} target="_blank" rel="noreferrer">{r}</a></div>
          ))}
        </section>
      )}
      {!f.description && !f.impact && !f.evidence && !f.remediation && <div className="small muted">no details recorded.</div>}
    </div>
  );
}

export function FindingsTable({ rows, loading, empty = "no findings filed yet.", events }: { rows: Finding[]; loading?: boolean; empty?: string; events?: RepoEvent[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const sorted = [...rows].sort(bySeverity);
  const eventOf = (id?: number | null) => (id == null ? null : events?.find((e) => e.id === id));
  return (
    <div className="box">
      <div className="thead" style={{ "--cols": COLS } as React.CSSProperties}>
        <span>severity</span><span>title</span><span>category</span><span>file:lines</span><span>introduced by</span><span>cwe / cve</span><span>confidence</span>
      </div>
      {sorted.map((f) => {
        const ev = eventOf(f.eventId);
        return (
          <div key={f.id}>
            <div className={`trow click${open === f.id ? " sel" : ""}`} style={{ "--cols": COLS } as React.CSSProperties} onClick={() => setOpen(open === f.id ? null : f.id)} title={open === f.id ? "collapse" : "expand"}>
              <span style={{ fontWeight: 700, color: sevColor(f.severity) }}>{f.severity}</span>
              <span className="ellip">
                <span className="muted">{open === f.id ? "▾ " : "▸ "}</span>
                {f.title || f.description?.split("\n")[0] || f.cwe || "untitled"}
                {ev && <span className="small muted"> · #{ev.id} {ev.action}</span>}
              </span>
              <span className="comment ellip">{f.category ?? "—"}</span>
              <span className="ellip" style={{ textDecoration: f.file ? "underline" : undefined }} title={loc(f)}>{loc(f)}</span>
              <Introduced f={f} />
              <span className="comment ellip">{[f.cwe, f.cve].filter(Boolean).join(" / ") || "—"}</span>
              <span className="comment">{f.confidence ?? "—"}</span>
            </div>
            {open === f.id && <Detail f={f} />}
          </div>
        );
      })}
      {rows.length === 0 && <div className="empty">{loading ? "loading…" : empty}</div>}
    </div>
  );
}

export interface FindingsSource {
  list: (f: FindingFilters) => Promise<Finding[]>;
  export: (format: FindingExportFormat, f: FindingFilters) => Promise<string>;
}

/** Filtered table + export. Filter options come from the unfiltered list, rows from the filtered one (both server-side). */
export function FindingsPanel({ source, events, empty, fileName = "findings" }: { source: FindingsSource; events?: RepoEvent[]; empty?: string; fileName?: string }) {
  const { say, fail } = useShell();
  const [f, setF] = useState<FindingFilters>({});
  const [busy, setBusy] = useState<FindingExportFormat | null>(null);
  const key = JSON.stringify(f);
  const allQ = useAsync(() => source.list({}), [source]);
  const rowsQ = useAsync(() => source.list(f), [source, key]);
  const all = allQ.data ?? [];
  const uniq = (xs: (string | null | undefined)[]) => [...new Set(xs.filter((x): x is string => !!x))];
  const severities = uniq(all.map((x) => x.severity)).sort((a, b) => sevRank(a) - sevRank(b));
  const categories = uniq(all.map((x) => x.category)).sort();
  const eventIds = uniq(all.map((x) => (x.eventId != null ? String(x.eventId) : null))).map(Number).sort((a, b) => b - a);
  const active = Object.values(f).some((v) => v !== undefined && v !== "");

  const doExport = async (format: FindingExportFormat) => {
    setBusy(format);
    try {
      const body = await source.export(format, f);
      if (format === "md") {
        await navigator.clipboard.writeText(body);
        say(`copied ${rowsQ.data?.length ?? ""} findings as a markdown table`);
      } else {
        const url = URL.createObjectURL(new Blob([body], { type: "text/csv" }));
        const a = Object.assign(document.createElement("a"), { href: url, download: `${fileName}.csv` });
        a.click();
        URL.revokeObjectURL(url);
        say(`exported ${fileName}.csv`);
      }
    } catch (e) {
      fail(e, "export failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
      <div className="row">
        <select className="select" value={f.severity ?? ""} onChange={(e) => setF({ ...f, severity: e.target.value || undefined })}>
          <option value="">any severity</option>
          {severities.map((s) => (<option key={s} value={s}>{s}</option>))}
        </select>
        <select className="select" value={f.category ?? ""} onChange={(e) => setF({ ...f, category: e.target.value || undefined })}>
          <option value="">any category</option>
          {categories.map((c) => (<option key={c} value={c}>{c}</option>))}
        </select>
        <select className="select" value={f.introducedBy ?? ""} onChange={(e) => setF({ ...f, introducedBy: (e.target.value || undefined) as IntroducedBy | undefined })}>
          <option value="">introduced any time</option>
          <option value="this_event">this event</option>
          <option value="earlier">earlier</option>
        </select>
        <select className="select" value={f.eventId ?? ""} onChange={(e) => setF({ ...f, eventId: e.target.value ? Number(e.target.value) : undefined })}>
          <option value="">any event</option>
          {eventIds.map((id) => { const ev = events?.find((e) => e.id === id); return <option key={id} value={id}>#{id}{ev ? ` ${ev.action} @ ${sha(ev.commitSha)}` : ""}</option>; })}
        </select>
        {active && <button className="btn sm" onClick={() => setF({})}>✕ clear</button>}
        <span className="small muted">{rowsQ.data ? `${rowsQ.data.length}${active ? ` of ${all.length}` : ""}` : "…"}</span>
        <span style={{ flex: 1 }} />
        <button className="btn sm" disabled={busy != null || !rowsQ.data?.length} onClick={() => doExport("csv")}>{busy === "csv" ? "…" : "↓ export csv"}</button>
        <button className="btn sm" disabled={busy != null || !rowsQ.data?.length} onClick={() => doExport("md")}>{busy === "md" ? "…" : "⎘ copy as markdown table"}</button>
      </div>
      {rowsQ.error && <div className="err small">{rowsQ.error.message}</div>}
      <FindingsTable rows={rowsQ.data ?? []} loading={rowsQ.loading && rowsQ.data === undefined} events={events} empty={active ? "nothing matches these filters." : empty} />
    </div>
  );
}

/* ── structured report ────────────────────────────────────────────── */
function List({ label, items, glyph = "·" }: { label: string; items?: string[] | null; glyph?: string }) {
  if (!items?.length) return null;
  return (
    <section>
      <div className="flabel" style={{ marginBottom: 4 }}>{label}</div>
      {items.map((x, i) => (
        <div key={i} className="pretty" style={{ display: "grid", gridTemplateColumns: "2ch 1fr", gap: 4 }}>
          <span className="accent">{glyph}</span><Rich>{x}</Rich>
        </div>
      ))}
    </section>
  );
}

/** Structured report if present, otherwise the summary markdown. */
export function ReportView({ report }: { report: Report }) {
  const s = report.structured;
  if (!s) return <Rich>{report.summary}</Rich>;
  const scope = s.scope;
  const files = Array.isArray(scope?.filesTouched) ? scope.filesTouched : null;
  const commit = report.commitSha ?? scope?.commit ?? null;
  const rng = scope?.range;
  const range = typeof rng === "string" ? rng : rng ? (rng.base && rng.head ? `${rng.base.slice(0, 7)}...${rng.head.slice(0, 7)}` : rng.before && rng.after ? `${rng.before.slice(0, 7)}..${rng.after.slice(0, 7)}` : "") : "";
  const sev = Object.entries(s.findingsBySeverity ?? {}).sort(([a], [b]) => sevRank(a) - sevRank(b));
  return (
    <div className="report">
      {(scope || sev.length > 0) && (
        <div className="report-head">
          {scope && (
            <div className="small comment">
              <b>scope</b> · {report.action ?? scope.eventType ?? "—"}{commit ? <> @ <b title={commit}>{commit.slice(0, 7)}</b></> : ""}{range ? ` · ${range}` : ""}
              {files ? ` · ${files.length} files` : typeof scope.filesTouched === "number" ? ` · ${scope.filesTouched} files` : ""}
              {scope.linesChanged != null ? ` · ${scope.linesChanged} lines` : ""}
              {files && <div className="muted ellip" title={files.join("\n")}>{files.join(", ")}</div>}
            </div>
          )}
          {sev.length > 0 && (
            <div className="small" style={{ display: "flex", gap: 10 }}>
              <b>findings</b>
              {sev.map(([k, n]) => (<span key={k} style={{ color: sevColor(k), fontWeight: 700 }}>{n} {k}</span>))}
            </div>
          )}
          {sev.length === 0 && s.findingsBySeverity && <div className="small muted">no findings</div>}
        </div>
      )}
      {(s.summary || report.summary) && <Rich>{s.summary || report.summary}</Rich>}
      <List label="top risks" items={s.topRisks} glyph="!" />
      <List label="recommendations" items={s.recommendations} glyph="→" />
      <List label="limitations" items={s.limitations} glyph="–" />
      {!!s.method?.length && <div className="small muted">method · {s.method.join(" · ")}</div>}
    </div>
  );
}
