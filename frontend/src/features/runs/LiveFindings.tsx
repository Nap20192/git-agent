/** Live findings panel — findings come from report_finding events, so they show
 *  up as soon as the agent (or a sub-agent) records them, not only at run end.
 *  Polls while the run is live; one final fetch once it's terminal. */
import { useEffect, useState } from "react";
import { useApi } from "@/api";
import type { Finding, ReportMeta } from "@/api";
import { Panel, PanelHeader } from "@/components/primitives";
import { FindingCard, SeverityBar } from "./findings-ui.tsx";
import styles from "./report.module.css";

export function LiveFindings({ runId, live }: { runId: string; live: boolean }) {
  const api = useApi();
  const [data, setData] = useState<{ findings: Finding[]; meta: ReportMeta } | null>(null);

  useEffect(() => {
    let ok = true;
    const load = () =>
      api
        .getFindings(runId)
        .then((d) => ok && setData(d))
        .catch(() => {});
    load();
    if (!live) return () => void (ok = false);
    const t = setInterval(load, 3000);
    return () => {
      ok = false;
      clearInterval(t);
    };
  }, [api, runId, live]);

  const findings = data?.findings ?? [];
  return (
    <Panel style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <PanelHeader
        icon="⚠"
        iconTone="high"
        title="FINDINGS"
        right={
          <span>
            {findings.length}
            {live ? " · live" : ""}
          </span>
        }
      />
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {data?.meta && data.meta.total > 0 && <SeverityBar meta={data.meta} />}
        {findings.length === 0 ? (
          <div className={styles.emptyDim} style={{ padding: 14 }}>
            {live ? "agent hasn't recorded findings yet…" : "no vulnerabilities recorded"}
          </div>
        ) : (
          <div className={styles.findings} style={{ padding: 10 }}>
            {findings.map((f, i) => (
              <FindingCard key={`${f.title}-${i}`} f={f} />
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}
