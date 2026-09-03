/** Instance detail: status + stop, reports, findings, and chat with the agent. */
import { useParams } from "react-router-dom";
import { useState } from "react";
import { useHubApi, type Finding } from "@/api/hub";
import { useBuilds, useHubRepositories, useInstance, useInstanceFindings, useInstanceReports } from "@/hooks";
import { Badge, Button, KeyValueList, Panel, PanelHeader, StatusDot } from "@/components/primitives";
import type { Tone } from "@/lib/tone.ts";
import { InstanceChatPanel } from "./InstanceChatPanel.tsx";
import { instanceTone } from "./InstancesScreen.tsx";
import styles from "./hub.module.css";

const SEVERITY_TONES: Record<string, Tone> = { critical: "crit", crit: "crit", high: "high", med: "med", medium: "med", low: "low" };
const severityTone = (s: string): Tone => SEVERITY_TONES[s.toLowerCase()] ?? "info";

export function InstanceScreen() {
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const api = useHubApi();
  const instQ = useInstance(id);
  const reportsQ = useInstanceReports(id);
  const findingsQ = useInstanceFindings(id);
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const [busy, setBusy] = useState(false);

  const inst = instQ.data;
  const repo = (reposQ.data ?? []).find((r) => r.id === inst?.repositoryId);
  const build = (buildsQ.data ?? []).find((b) => b.id === inst?.buildId);

  // Only gate on the FIRST load — reloads (e.g. after chat wakes the
  // instance) keep the screen and the session-local chat transcript mounted.
  if (!inst && instQ.loading) return <div className={styles.gate}>loading…</div>;
  if (!inst) {
    return (
      <div className={styles.gate}>
        <span style={{ color: "var(--crit)", fontSize: 12 }}>{instQ.error?.message ?? "instance not found"}</span>
      </div>
    );
  }

  const stop = async () => {
    setBusy(true);
    try {
      await api.stopInstance(inst.id);
      instQ.reload();
    } finally {
      setBusy(false);
    }
  };

  const reports = reportsQ.data ?? [];
  const findings = findingsQ.data ?? [];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>
            instance #{inst.id}
            {repo && <span style={{ color: "var(--muted)" }}> — {repo.owner}/{repo.name}</span>}
          </h1>
          <span className={styles.dotCell}>
            <StatusDot tone={instanceTone(inst.status)} pulse={inst.status === "running"} />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>{inst.status}</span>
          </span>
          <div style={{ flex: 1 }} />
          {inst.status === "running" && (
            <Button variant="ghost" disabled={busy} onClick={stop}>
              ■ stop
            </Button>
          )}
        </div>
        <p className={styles.blurb}>
          one checkpoint thread accumulating knowledge of this repository. Stopping parks it (checkpoint stays);
          the next Событие or chat message wakes it.
        </p>

        <div className={styles.detailGrid}>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Panel>
              <PanelHeader icon="◈" title="META" />
              <div style={{ padding: "10px 12px" }}>
                <KeyValueList
                  rows={[
                    { key: "Сборка", value: build?.name ?? `#${inst.buildId}` },
                    { key: "thread", value: inst.threadId ?? "—", tone: "dim" },
                    { key: "runner", value: inst.runnerId != null ? `#${inst.runnerId}` : "—" },
                    { key: "sandbox", value: inst.sandboxInstanceId != null ? `#${inst.sandboxInstanceId}` : "—" },
                    { key: "updated", value: inst.updatedAt ? new Date(inst.updatedAt).toLocaleString() : "—" },
                  ]}
                />
              </div>
            </Panel>

            <Panel>
              <PanelHeader icon="≡" title="REPORTS" right={<span className={styles.cell}>{reports.length}</span>} />
              {reports.length === 0 && <div className={styles.panelEmpty}>{reportsQ.loading ? "loading…" : "no reports yet"}</div>}
              {reports.map((r) => (
                <div key={r.id} className={styles.reportItem}>
                  <div className={styles.reportMeta}>
                    <span>{new Date(r.createdAt).toLocaleString()}</span>
                    {r.eventId != null && <span>Событие #{r.eventId}</span>}
                  </div>
                  {r.summary}
                </div>
              ))}
            </Panel>

            <Panel>
              <PanelHeader icon="⚠" title="FINDINGS" right={<span className={styles.cell}>{findings.length}</span>} />
              {findings.length === 0 && <div className={styles.panelEmpty}>{findingsQ.loading ? "loading…" : "no findings"}</div>}
              {findings.map((f) => (
                <FindingRow key={f.id} finding={f} />
              ))}
            </Panel>
          </div>

          <InstanceChatPanel instanceId={inst.id} onStatusChange={instQ.reload} />
        </div>
      </div>
    </div>
  );
}

function FindingRow({ finding: f }: { finding: Finding }) {
  return (
    <div className={styles.findingItem}>
      <div className={styles.findingHead}>
        <Badge tone={severityTone(f.severity)} uppercase>
          {f.severity}
        </Badge>
        {f.cwe && <span className={styles.cell}>{f.cwe}</span>}
        {f.cve && <span className={styles.cell}>{f.cve}</span>}
        {f.file && (
          <span className={styles.findingFile}>
            {f.file}
            {f.lineStart != null && `:${f.lineStart}${f.lineEnd != null && f.lineEnd !== f.lineStart ? `–${f.lineEnd}` : ""}`}
          </span>
        )}
      </div>
      {f.evidence && <div className={styles.findingEvidence}>{f.evidence}</div>}
      {f.remediation && <div style={{ color: "var(--muted)" }}>{f.remediation}</div>}
    </div>
  );
}
