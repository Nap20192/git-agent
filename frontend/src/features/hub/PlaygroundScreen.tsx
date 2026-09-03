/** Playground — live view of one agent Экземпляр, Railway-deploy style:
 *  status strip (runner, sandbox, slots, pulse), Событие timeline with
 *  processing status, activity log, findings as they land, and chat.
 *  Liveness is a 5s poll — the hub contract has no status/activity stream yet
 *  (only chat SSE); the gaps are listed in frontend/PLAYGROUND-TODO.md. */
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { RepoEvent, Report } from "@/api/hub";
import {
  useBuilds,
  useHubRepositories,
  useInstance,
  useInstanceFindings,
  useInstanceReports,
  useInstances,
  useRepoEvents,
  useRunners,
} from "@/hooks";
import { useHubApi } from "@/api/hub";
import { Badge, Button, Panel, PanelHeader } from "@/components/primitives";
import { InstanceChatPanel } from "./InstanceChatPanel.tsx";
import { InstanceTerminalPanel } from "./InstanceTerminalPanel.tsx";
import { FindingRow } from "./RepoScreen.tsx";
import styles from "./hub.module.css";

const POLL_MS = 5000;

interface ActivityLine {
  at: Date;
  text: string;
}

export function PlaygroundScreen() {
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const navigate = useNavigate();
  const api = useHubApi();

  const instQ = useInstance(id);
  const inst = instQ.data;
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const runnersQ = useRunners();
  const instancesQ = useInstances();
  const eventsQ = useRepoEvents(inst?.repositoryId ?? null);
  const findingsQ = useInstanceFindings(id);
  const reportsQ = useInstanceReports(id);

  const [activity, setActivity] = useState<ActivityLine[]>([]);
  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);

  // Poll everything the screen shows. reload identities change every render,
  // so the interval reads them through a ref instead of re-arming.
  const reloadRef = useRef(() => {});
  reloadRef.current = () => {
    instQ.reload();
    eventsQ.reload();
    findingsQ.reload();
    reportsQ.reload();
    runnersQ.reload();
    instancesQ.reload();
  };
  useEffect(() => {
    const t = setInterval(() => reloadRef.current(), POLL_MS);
    return () => clearInterval(t);
  }, []);

  if (instQ.error || (inst == null && !instQ.loading)) {
    return (
      <div className={styles.gate}>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          {instQ.error ? `Failed to load Экземпляр #${id}: ${instQ.error.message}` : `Экземпляр #${id} not found.`}
        </span>
      </div>
    );
  }
  if (inst == null) {
    return (
      <div className={styles.gate}>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>loading…</span>
      </div>
    );
  }

  const repo = (reposQ.data ?? []).find((r) => r.id === inst.repositoryId);
  const build = (buildsQ.data ?? []).find((b) => b.id === inst.buildId);
  const runner = inst.runnerId != null ? (runnersQ.data ?? []).find((r) => r.id === inst.runnerId) : undefined;
  // Busy slots = running instances placed on this runner (derived; the wire has no busy counter).
  const busySlots = runner
    ? (instancesQ.data ?? []).filter((i) => i.runnerId === runner.id && i.status === "running").length
    : 0;

  const events = eventsQ.data ?? [];
  const reports = reportsQ.data ?? [];
  const findings = [...(findingsQ.data ?? [])].reverse();
  const reportFor = (e: RepoEvent): Report | undefined => reports.find((r) => r.eventId === e.id);
  const running = inst.status === "running";

  const runAgent = async () => {
    setTriggering(true);
    setTriggerError(null);
    try {
      const res = await api.triggerRepository(inst.repositoryId);
      setActivity((a) => [
        ...a,
        { at: new Date(), text: `manual trigger → Событие #${res.event.id} @ ${res.event.commitSha?.slice(0, 8) ?? "HEAD"}` },
      ]);
      reloadRef.current();
    } catch (err) {
      setTriggerError(err instanceof Error ? err.message : "trigger failed");
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <span className={styles.backLink} onClick={() => navigate(repo ? `/repos/${repo.id}` : "/repos")}>
          ← {repo ? `${repo.owner}/${repo.name}` : "repositories"}
        </span>
        <div className={styles.head}>
          <h1 className={styles.title}>
            <span className={styles.cardOwner}>playground/</span>
            {build?.name ?? `Экземпляр #${inst.id}`}
          </h1>
          {repo && <Badge tone={repo.provider === "github" ? "text" : "burnt"}>{repo.provider}</Badge>}
          <div style={{ flex: 1 }} />
          <Button variant="primary" disabled={triggering} onClick={runAgent}>
            {triggering ? "Triggering…" : "▶ Run agent"}
          </Button>
        </div>
        {triggerError && <p className={styles.error}>{triggerError}</p>}
        <p className={styles.blurb}>
          Live view of this agent: what arrives, what it does, what it finds. Everything refreshes on its own.
        </p>

        <div className={styles.statusStrip}>
          <div className={styles.statusItem}>
            <span className={styles.statusLabel}>agent</span>
            <span className={styles.statusValue}>
              <span className={`${styles.presenceDot} ${running ? styles.awake : styles.asleep}`} />
              {running ? "running" : "down"}
            </span>
          </div>
          <div className={styles.statusItem}>
            <span className={styles.statusLabel}>runner</span>
            <span className={styles.statusValue}>
              {runner ? (
                <>
                  {runner.name} <span className={styles.mono}>{runner.address}</span>
                </>
              ) : (
                "—"
              )}
            </span>
          </div>
          <div className={styles.statusItem}>
            <span className={styles.statusLabel}>slots</span>
            <span className={styles.statusValue}>{runner ? `${busySlots} / ${runner.slots}` : "—"}</span>
          </div>
          <div className={styles.statusItem}>
            <span className={styles.statusLabel}>sandbox</span>
            <span className={styles.statusValue}>
              {inst.sandboxInstanceId != null ? <span className={styles.mono}>#{inst.sandboxInstanceId}</span> : "none"}
            </span>
          </div>
          <div className={styles.statusItem}>
            <span className={styles.statusLabel}>updated</span>
            <span className={styles.statusValue}>
              {inst.updatedAt ? new Date(inst.updatedAt).toLocaleTimeString() : "—"}
            </span>
          </div>
        </div>

        <div className={styles.repoGrid}>
          <div className={styles.rail}>
            <Panel>
              <PanelHeader
                icon="↯"
                title="TIMELINE — СОБЫТИЯ"
                right={<span className={styles.cell}>{events.length}</span>}
              />
              <div className={styles.timeline}>
                {events.length === 0 && (
                  <div className={styles.journalEmpty}>
                    {eventsQ.loading && eventsQ.data === undefined
                      ? "loading…"
                      : "Nothing yet. Push to the repository and the webhook delivers the first Событие here."}
                  </div>
                )}
                {events.map((e) => {
                  const report = reportFor(e);
                  return (
                    <div key={e.id} className={styles.tlRow}>
                      <span className={`${styles.tlDot} ${report ? styles.tlDone : running ? styles.tlPending : ""}`} />
                      <div className={styles.tlBody}>
                        <div className={styles.tlHead}>
                          <span className={styles.tlAction}>
                            {e.provider} · {e.action}
                          </span>
                          {e.commitSha && <span className={styles.tlMeta}>{e.commitSha.slice(0, 8)}</span>}
                          {e.ref && <span className={styles.tlMeta}>{e.ref}</span>}
                          <span className={styles.tlTime}>{new Date(e.receivedAt).toLocaleString()}</span>
                        </div>
                        <div className={styles.tlReport}>
                          {report
                            ? `✓ processed — ${report.summary}`
                            : running
                              ? "no report yet — processing or queued"
                              : "no report — agent is down"}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Panel>

            <Panel>
              <PanelHeader
                icon="⚙"
                title="ACTIVITY"
                right={<span className={styles.cell}>{activity.length}</span>}
              />
              <div className={styles.activityLog}>
                {activity.length === 0 && (
                  <div className={styles.panelEmpty}>
                    No activity captured yet. The hub streams agent activity only inside chat for now — talk to the
                    agent and its working steps land here. A per-Событие activity stream is on the backend wishlist
                    (PLAYGROUND-TODO.md).
                  </div>
                )}
                {activity.map((a, i) => (
                  <div key={i} className={styles.activityRow}>
                    <span className={styles.activityTime}>{a.at.toLocaleTimeString()}</span>
                    <span className={styles.activityText}>{a.text}</span>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel>
              <PanelHeader
                icon="⚠"
                title="FINDINGS"
                right={<span className={styles.cell}>{findings.length}</span>}
              />
              {findings.length === 0 && (
                <div className={styles.panelEmpty}>
                  {findingsQ.loading && findingsQ.data === undefined ? "loading…" : "No findings — clean so far."}
                </div>
              )}
              {findings.map((f) => (
                <FindingRow key={f.id} finding={f} />
              ))}
            </Panel>
          </div>

          <div className={styles.rail}>
            <InstanceChatPanel
              instanceId={inst.id}
              agentLabel={build?.name}
              onStatusChange={() => {
                instQ.reload();
                instancesQ.reload();
              }}
              onActivity={(text) => setActivity((a) => [...a, { at: new Date(), text }])}
            />

            <InstanceTerminalPanel
              instanceId={inst.id}
              running={running}
              hasSandbox={inst.sandboxInstanceId != null}
            />

            <Panel>
              <PanelHeader icon="≡" title="REPORTS" right={<span className={styles.cell}>{reports.length}</span>} />
              {reports.length === 0 && (
                <div className={styles.panelEmpty}>
                  {reportsQ.loading && reportsQ.data === undefined
                    ? "loading…"
                    : "No reports yet — the agent writes one after working through a Событие."}
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
          </div>
        </div>
      </div>
    </div>
  );
}
