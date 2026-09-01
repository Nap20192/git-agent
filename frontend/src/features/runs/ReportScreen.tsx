/** Report screen: the parse/report output for a finished run — description,
 *  repo structure, modules, and dependencies. Read-only. */
import { useNavigate, useParams } from "react-router-dom";
import { useReport } from "@/hooks";
import { Badge, KeyValueList, Meter, Panel, PanelHeader } from "@/components/primitives";
import type { KeyValueRow } from "@/components/primitives";
import type { Finding, Severity } from "@/api";
import styles from "./report.module.css";

const SEVERITY_TONE: Record<Severity, "crit" | "high" | "amber" | "muted"> = {
  critical: "crit",
  high: "high",
  medium: "amber",
  low: "muted",
  info: "muted",
};
const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

function FindingsPanel({ findings }: { findings: Finding[] }) {
  const counts = SEVERITY_ORDER.map(
    (s) => [s, findings.filter((f) => f.severity === s).length] as const,
  ).filter(([, n]) => n > 0);
  return (
    <Panel className={styles.section}>
      <PanelHeader icon="⚠" iconTone="high" title="FINDINGS" right={<span>{findings.length}</span>} />
      <div className={styles.chips}>
        {counts.length === 0 ? (
          <span className={styles.emptyDim}>no findings</span>
        ) : (
          counts.map(([s, n]) => (
            <Badge key={s} tone={SEVERITY_TONE[s]}>
              {s} · {n}
            </Badge>
          ))
        )}
      </div>
      <div className={styles.findings}>
        {findings.map((f, i) => (
          <div key={`${f.title}-${i}`} className={styles.finding}>
            <div className={styles.findingHead}>
              <Badge tone={SEVERITY_TONE[f.severity]}>{f.severity}</Badge>
              <span className={styles.findingTitle}>{f.title}</span>
              {f.cwe && <span className={styles.findingTag}>{f.cwe}</span>}
              {f.cve && <span className={styles.findingTag}>{f.cve}</span>}
            </div>
            {f.file && (
              <div className={styles.findingLoc}>
                {f.file}
                {f.startLine ? `:${f.startLine}` : ""}
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
          </div>
        ))}
      </div>
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
            {report.findings && <FindingsPanel findings={report.findings} />}

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
