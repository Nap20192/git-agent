/** Shared findings rendering — used by the final ReportScreen and the live
 *  findings panel on the run detail. Findings are derived from report_finding
 *  events, so the same cards render mid-run and at completion. */
import type { ReactNode } from "react";
import { Badge } from "@/components/primitives";
import type { Finding, ReportMeta, Severity } from "@/api";
import styles from "./report.module.css";

export const SEVERITY_TONE: Record<Severity, "crit" | "high" | "amber" | "muted"> = {
  critical: "crit",
  high: "high",
  medium: "amber",
  low: "muted",
  info: "muted",
};
export const SEVERITY_COLOR: Record<Severity, string> = {
  critical: "var(--crit)",
  high: "var(--high)",
  medium: "var(--amber, #d9a441)",
  low: "var(--low, #6b8caf)",
  info: "var(--muted)",
};
export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

// подсветка важного: `код`/**жирный** → чипы, плюс пути и id-вроде-кода (CWE/CVE)
const TOKEN_RE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\b[\w./-]+\.[a-z]{1,4}(?::\d+(?:-\d+)?)?)|(\bCWE-\d+|\bCVE-\d{4}-\d+)/g;

export function RichText({ text }: { text: string }) {
  if (!text) return null;
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  let k = 0;
  while ((m = TOKEN_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const [, code, bold, path, id] = m;
    if (code) out.push(<code key={k++} className={styles.hlCode}>{code.slice(1, -1)}</code>);
    else if (bold) out.push(<strong key={k++} className={styles.hlBold}>{bold.slice(2, -2)}</strong>);
    else if (path) out.push(<code key={k++} className={styles.hlPath}>{path}</code>);
    else if (id) out.push(<span key={k++} className={styles.hlId}>{id}</span>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

export function severityHeadline(meta: ReportMeta): { s: Severity; n: number }[] {
  return SEVERITY_ORDER.map((s) => ({ s, n: meta.severityCounts[s] })).filter((x) => x.n > 0);
}

/** Horizontal severity distribution bar + per-severity counts. */
export function SeverityBar({ meta }: { meta: ReportMeta }) {
  const total = meta.total || 1;
  const present = SEVERITY_ORDER.filter((s) => meta.severityCounts[s] > 0);
  return (
    <div className={styles.sevWrap}>
      <div className={styles.sevBar}>
        {present.map((s) => (
          <div
            key={s}
            className={styles.sevSeg}
            style={{ width: `${(meta.severityCounts[s] / total) * 100}%`, background: SEVERITY_COLOR[s] }}
            title={`${s}: ${meta.severityCounts[s]}`}
          />
        ))}
      </div>
      <div className={styles.sevLegend}>
        {SEVERITY_ORDER.map((s) => (
          <span key={s} className={styles.sevItem} data-zero={meta.severityCounts[s] === 0}>
            <span className={styles.sevDot} style={{ background: SEVERITY_COLOR[s] }} />
            {s} <b>{meta.severityCounts[s]}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

export function FindingCard({ f }: { f: Finding }) {
  return (
    <div className={styles.finding} style={{ borderLeftColor: SEVERITY_COLOR[f.severity] }}>
      <div className={styles.findingHead}>
        <Badge tone={SEVERITY_TONE[f.severity]}>{f.severity}</Badge>
        <span className={styles.findingTitle}>{f.title}</span>
        <span className={styles.findingSpacer} />
        {f.cwe && <span className={styles.findingTag}>{f.cwe}</span>}
        {f.cve && <span className={styles.findingTag}>{f.cve}</span>}
        {f.agent && <span className={styles.findingAgent}>◆ {f.agent}</span>}
      </div>
      {f.file && (
        <div className={styles.findingLoc}>
          {f.file}
          {f.startLine ? `:${f.startLine}${f.endLine && f.endLine !== f.startLine ? `-${f.endLine}` : ""}` : ""}
        </div>
      )}
      <p className={styles.findingDesc}>
        <RichText text={f.description} />
      </p>
      {f.evidence && <pre className={styles.findingEvidence}>{f.evidence}</pre>}
      {f.impact && (
        <p className={styles.findingMeta}>
          <span className={styles.findingMetaLabel} data-kind="impact">impact</span>{" "}
          <RichText text={f.impact} />
        </p>
      )}
      {f.remediation && (
        <p className={styles.findingMeta}>
          <span className={styles.findingMetaLabel} data-kind="fix">fix</span>{" "}
          <RichText text={f.remediation} />
        </p>
      )}
      {f.confidence && (
        <p className={styles.findingMeta}>
          <span className={styles.findingMetaLabel}>confidence</span>{" "}
          <RichText text={f.confidence} />
        </p>
      )}
    </div>
  );
}
