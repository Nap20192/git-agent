/** Reports — a dedicated browse surface for finished runs' reports. Each card
 *  shows the repo, model, status and a severity summary of the findings, and
 *  opens the full report. Reports are derived from finished runs (runs.report). */
import { useNavigate } from "react-router-dom";
import { useReports } from "@/hooks";
import { StatusBadge } from "@/components/primitives";
import type { ReportCard, Severity } from "@/api";
import { SEVERITY_COLOR, SEVERITY_ORDER } from "@/features/runs/findings-ui.tsx";
import styles from "./ReportsScreen.module.css";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function Card({ r }: { r: ReportCard }) {
  const navigate = useNavigate();
  const present = r.findings
    ? SEVERITY_ORDER.filter((s) => r.findings!.severityCounts[s] > 0)
    : [];
  return (
    <div className={styles.card} onClick={() => navigate(`/runs/${r.runId}/report`)}>
      <div className={styles.head}>
        <span className={styles.repo}>{r.repo}</span>
        <StatusBadge status={r.status} />
      </div>
      <div className={styles.meta}>
        <span className={styles.commit}>{r.commit.slice(0, 7) || "—"}</span>
        <span className={styles.model}>{r.model || "—"}</span>
        <span className={styles.date}>{fmtDate(r.finishedAt)}</span>
      </div>
      {r.findings ? (
        <div className={styles.sevRow}>
          {present.length === 0 ? (
            <span className={styles.clean}>no vulnerabilities</span>
          ) : (
            present.map((s: Severity) => (
              <span
                key={s}
                className={styles.sevChip}
                style={{ borderColor: SEVERITY_COLOR[s], color: SEVERITY_COLOR[s] }}
              >
                {r.findings!.severityCounts[s]} {s}
              </span>
            ))
          )}
          <span className={styles.total}>{r.findings.total} findings</span>
        </div>
      ) : (
        <div className={styles.pipeline}>pipeline report · no findings</div>
      )}
      <div className={styles.open}>open report →</div>
    </div>
  );
}

export function ReportsScreen() {
  const reportsQ = useReports();
  const reports = reportsQ.data ?? [];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.headerBar}>
          <h1 className={styles.title}>reports</h1>
          <span className={styles.path}>~/git-agent/reports</span>
          <div style={{ flex: 1 }} />
          <span className={styles.count}>{reports.length}</span>
        </div>
        <p className={styles.muted}>
          finished runs and their reports — findings severity at a glance; open one for the full write-up.
        </p>
        {reports.length === 0 ? (
          <div className={styles.empty}>{reportsQ.loading ? "loading…" : "no reports yet"}</div>
        ) : (
          <div className={styles.grid}>
            {reports.map((r) => (
              <Card key={r.runId} r={r} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
