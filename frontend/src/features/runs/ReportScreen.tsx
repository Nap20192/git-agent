/** Report screen: the parse/report output for a finished run — description,
 *  repo structure, modules, and dependencies. Read-only. */
import { useNavigate, useParams } from "react-router-dom";
import { useReport } from "@/hooks";
import { Badge, KeyValueList, Meter, Panel, PanelHeader } from "@/components/primitives";
import type { KeyValueRow } from "@/components/primitives";
import type { Finding, ReportMeta, Severity } from "@/api";
import styles from "./report.module.css";

const SEVERITY_TONE: Record<Severity, "crit" | "high" | "amber" | "muted"> = {
  critical: "crit",
  high: "high",
  medium: "amber",
  low: "muted",
  info: "muted",
};
const SEVERITY_COLOR: Record<Severity, string> = {
  critical: "var(--crit)",
  high: "var(--high)",
  medium: "var(--amber, #d9a441)",
  low: "var(--low, #6b8caf)",
  info: "var(--muted)",
};
const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

/** Horizontal severity distribution bar + per-severity counts. */
function SeverityBar({ meta }: { meta: ReportMeta }) {
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

function FindingCard({ f }: { f: Finding }) {
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
      <p className={styles.findingDesc}>{f.description}</p>
      {f.evidence && <pre className={styles.findingEvidence}>{f.evidence}</pre>}
      {f.impact && (
        <p className={styles.findingMeta}>
          <span className={styles.findingMetaLabel}>impact</span> {f.impact}
        </p>
      )}
      {f.remediation && (
        <p className={styles.findingMeta}>
          <span className={styles.findingMetaLabel}>fix</span> {f.remediation}
        </p>
      )}
      {f.confidence && (
        <p className={styles.findingMeta}>
          <span className={styles.findingMetaLabel}>confidence</span> {f.confidence}
        </p>
      )}
    </div>
  );
}

function FindingsPanel({ findings, meta }: { findings: Finding[]; meta?: ReportMeta }) {
  return (
    <Panel className={styles.section}>
      <PanelHeader
        icon="⚠"
        iconTone="high"
        title="FINDINGS"
        right={
          <span>
            {findings.length}
            {meta && meta.filesReviewed > 0 ? ` · ${meta.filesReviewed} files` : ""}
          </span>
        }
      />
      {meta && meta.total > 0 && <SeverityBar meta={meta} />}
      {findings.length === 0 ? (
        <div className={styles.emptyDim}>no vulnerabilities recorded</div>
      ) : (
        <div className={styles.findings}>
          {findings.map((f, i) => (
            <FindingCard key={`${f.title}-${i}`} f={f} />
          ))}
        </div>
      )}
    </Panel>
  );
}

/** Byte count -> "12.3 KB" / "4.1 MB". */
function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

export function ReportScreen() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const report = useReport(id).data;

  if (report === undefined) return <div className={styles.loading}>loading report…</div>;

  const { structure } = report;
  const langs = Object.entries(structure.languages).sort((a, b) => b[1] - a[1]);
  const maxCount = langs.reduce((m, [, c]) => Math.max(m, c), 0) || 1;

  const structRows: KeyValueRow[] = [
    { key: "files", value: structure.fileCount },
    { key: "size", value: bytes(structure.totalBytes) },
    { key: "truncated", value: structure.truncated ? "yes" : "no", tone: structure.truncated ? "high" : "muted" },
  ];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <button type="button" className={styles.back} onClick={() => navigate(`/runs/${id}`)}>
            ← run
          </button>
          <h1 className={styles.title}>report</h1>
          <span className={styles.meta}>{report.repoUrl}</span>
          <span className={styles.meta}>{report.commit.slice(0, 7)}</span>
        </div>

        {report.error ? (
          <Panel className={styles.section}>
            <PanelHeader icon="✕" iconTone="crit" title="ERROR" />
            <div className={styles.error}>{report.error}</div>
          </Panel>
        ) : (
          <>
            {report.findings && <FindingsPanel findings={report.findings} meta={report.meta} />}

            <Panel className={styles.section}>
              <PanelHeader icon="◈" title={report.findings ? "SUMMARY" : "DESCRIPTION"} />
              <p className={styles.prose}>{report.summary || report.description}</p>
            </Panel>

            {structure.fileCount > 0 && (
            <>
            <Panel className={styles.section}>
              <PanelHeader icon="▤" title="STRUCTURE" right={<span>{structure.fileCount} files</span>} />
              <KeyValueList rows={structRows} />

              {langs.length > 0 && (
                <>
                  <div className={styles.subLabel}>LANGUAGES</div>
                  <div className={styles.langs}>
                    {langs.map(([ext, count]) => (
                      <div key={ext} className={styles.langRow}>
                        <span className={styles.langExt}>{ext}</span>
                        <Meter pct={(count / maxCount) * 100} tone="amber" width={160} />
                        <span className={styles.langCount}>{count}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {structure.keyFiles.length > 0 && (
                <>
                  <div className={styles.subLabel}>KEY FILES</div>
                  <div className={styles.chips}>
                    {structure.keyFiles.map((f) => (
                      <Badge key={f} tone="amber">
                        {f}
                      </Badge>
                    ))}
                  </div>
                </>
              )}
            </Panel>

            <Panel className={styles.section}>
              <PanelHeader icon="⬡" title="MODULES" right={<span>{report.modules.length}</span>} />
              <div className={styles.modules}>
                <div className={`${styles.moduleRow} ${styles.moduleHead}`}>
                  <span>PATH</span>
                  <span>CLASSES</span>
                  <span>FUNCTIONS</span>
                </div>
                {report.modules.map((m) => (
                  <div key={m.path} className={styles.moduleRow}>
                    <span className={styles.modPath} title={m.path}>
                      {m.path}
                    </span>
                    <span className={styles.modClasses}>{m.classes.join(", ") || "—"}</span>
                    <span className={styles.modFns}>{m.functions.length}</span>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel className={styles.section}>
              <PanelHeader icon="⊞" title="DEPENDENCIES" right={<span>{report.dependencies.length}</span>} />
              <div className={styles.chips}>
                {report.dependencies.length === 0 ? (
                  <span className={styles.emptyDim}>none</span>
                ) : (
                  report.dependencies.map((d) => (
                    <Badge key={d} tone="muted">
                      {d}
                    </Badge>
                  ))
                )}
              </div>
            </Panel>
            </>
            )}

            {report.skippedFiles.length > 0 && (
              <div className={styles.skipped}>{report.skippedFiles.length} files skipped</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
