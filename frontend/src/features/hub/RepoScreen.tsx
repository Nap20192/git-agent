/** Repository page — the agent's home. The Экземпляр is 1:1 with the repo, so
 *  everything about it lives here: presence + chat (hero), the Событие
 *  journal, reports, findings, and settings (Сборка binding, disconnect). */
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useHubApi, type AgentInstance, type Finding } from "@/api/hub";
import {
  useBuilds,
  useHubRepositories,
  useInstanceFindings,
  useInstanceReports,
  useInstances,
  useRepoEvents,
} from "@/hooks";
import { Badge, Button, Panel, PanelHeader } from "@/components/primitives";
import type { Tone } from "@/lib/tone.ts";
import { InstanceChatPanel } from "./InstanceChatPanel.tsx";
import { AgentPresence } from "./RepositoriesScreen.tsx";
import styles from "./hub.module.css";

const SEVERITY_TONES: Record<string, Tone> = {
  critical: "crit",
  crit: "crit",
  high: "high",
  med: "med",
  medium: "med",
  low: "low",
};
const severityTone = (s: string): Tone => SEVERITY_TONES[s.toLowerCase()] ?? "info";

export function RepoScreen() {
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const navigate = useNavigate();
  const api = useHubApi();

  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const instancesQ = useInstances();
  const eventsQ = useRepoEvents(id);
  const [busy, setBusy] = useState(false);

  const repo = (reposQ.data ?? []).find((r) => r.id === id);
  const instance = (instancesQ.data ?? []).find((i) => i.repositoryId === id);
  const builds = buildsQ.data ?? [];
  const events = eventsQ.data ?? [];

  if (!repo) {
    return (
      <div className={styles.gate}>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          {reposQ.loading ? "loading…" : "This repository isn't connected. Pick one from the repositories page."}
        </span>
      </div>
    );
  }

  const putToSleep = async () => {
    if (!instance) return;
    setBusy(true);
    try {
      await api.stopInstance(instance.id);
      instancesQ.reload();
    } finally {
      setBusy(false);
    }
  };

  const bindBuild = async (buildId: number) => {
    setBusy(true);
    try {
      await api.setRepositoryBuild(repo.id, buildId);
      reposQ.reload();
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    try {
      await api.disconnectRepository(repo.id);
      navigate("/repos");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <span className={styles.backLink} onClick={() => navigate("/repos")}>
          ← repositories
        </span>
        <div className={styles.head}>
          <h1 className={styles.title}>
            <span className={styles.cardOwner}>{repo.owner}/</span>
            {repo.name}
          </h1>
          <Badge tone={repo.provider === "github" ? "text" : "burnt"}>{repo.provider}</Badge>
          <AgentPresence instance={instance} />
          <div style={{ flex: 1 }} />
          {instance?.status === "running" && (
            <Button variant="ghost" disabled={busy} onClick={putToSleep}>
              Put to sleep
            </Button>
          )}
        </div>
        <p className={styles.blurb}>
          {instance
            ? "The agent keeps one thread of knowledge about this repository. It sleeps when idle — the next Событие or your next message wakes it."
            : "No agent yet — bind a Сборка below and the first Событие (or your first message) will start one."}
        </p>

        <div className={styles.repoGrid}>
          <InstanceChatPanel instanceId={instance?.id ?? null} onStatusChange={instancesQ.reload} />

          <div className={styles.rail}>
            <Panel>
              <PanelHeader
                icon="↯"
                title="JOURNAL — СОБЫТИЯ"
                right={<span className={styles.cell}>{events.length}</span>}
              />
              <div className={styles.journal}>
                {events.length === 0 && (
                  <div className={styles.journalEmpty}>
                    {eventsQ.loading ? "loading…" : "Nothing yet. Push to the repository and the webhook delivers the first Событие here."}
                  </div>
                )}
                {events.map((e) => (
                  <div key={e.id} className={styles.eventRow}>
                    <span className={styles.eventAction}>{e.action}</span>
                    <span className={styles.eventSha}>{e.commitSha?.slice(0, 8) ?? ""}</span>
                    <span className={styles.eventRef}>{e.ref ?? ""}</span>
                    <span className={styles.eventTime}>{new Date(e.receivedAt).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </Panel>

            {instance && <InstancePanels instance={instance} />}

            <Panel soft>
              <PanelHeader icon="✳" title="SETTINGS" />
              <div style={{ padding: "12px 14px" }}>
                <label className={styles.label}>Сборка</label>
                <select
                  className={styles.select}
                  value={repo.buildId ?? ""}
                  disabled={busy}
                  onChange={(e) => e.target.value && bindBuild(Number(e.target.value))}
                >
                  <option value="">— none —</option>
                  {builds.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                      {b.isDefault ? " (default)" : ""}
                    </option>
                  ))}
                </select>
                <div className={styles.actions}>
                  <Button variant="ghost" disabled={busy} onClick={disconnect}>
                    Disconnect repository
                  </Button>
                </div>
                <p className={styles.hint}>Disconnecting removes the webhook from the provider. The agent's knowledge stays in its checkpoint.</p>
              </div>
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Reports + findings — only mounted when the repo has an agent (hooks need its id). */
function InstancePanels({ instance }: { instance: AgentInstance }) {
  const reportsQ = useInstanceReports(instance.id);
  const findingsQ = useInstanceFindings(instance.id);
  const reports = reportsQ.data ?? [];
  const findings = findingsQ.data ?? [];

  return (
    <>
      <Panel>
        <PanelHeader icon="≡" title="REPORTS" right={<span className={styles.cell}>{reports.length}</span>} />
        {reports.length === 0 && (
          <div className={styles.panelEmpty}>
            {reportsQ.loading ? "loading…" : "No reports yet — the agent writes one after working through a Событие."}
          </div>
        )}
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
        {findings.length === 0 && (
          <div className={styles.panelEmpty}>{findingsQ.loading ? "loading…" : "No findings — clean so far."}</div>
        )}
        {findings.map((f) => (
          <FindingRow key={f.id} finding={f} />
        ))}
      </Panel>
    </>
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
