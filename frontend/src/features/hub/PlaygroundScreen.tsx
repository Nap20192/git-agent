/** Playground — live view of one agent Экземпляр, Railway-deploy style:
 *  status strip (runner, sandbox, slots, pulse), run graph «Лид → Сабагенты»
 *  fed by the activity SSE (ticket 012), Событие timeline (click an event to
 *  replay its ход on the graph), activity log, findings, chat. Entity lists
 *  still poll at 5s — only activity streams. */
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { RepoEvent, Report } from "@/api/hub";
import { activityLine, useInstanceActivity } from "./activity.ts";
import { InstanceGraphPanel } from "./InstanceGraphPanel.tsx";
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
  // null = follow the live/latest ход; a Событие id pins the graph to its replay
  const [graphEventId, setGraphEventId] = useState<number | null>(null);
  const { frames, done: turnDone } = useInstanceActivity(id, graphEventId);
  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [sandboxBusy, setSandboxBusy] = useState(false);
  const [sandboxError, setSandboxError] = useState<string | null>(null);

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
  // activity log = локальные действия экрана + строки activity-стрима хода
  const streamLines = frames.flatMap((f) => {
    const text = activityLine(f);
    return text ? [{ at: f.ts ? new Date(f.ts) : new Date(), text }] : [];
  });
  const log = [...activity, ...streamLines].sort((a, b) => a.at.getTime() - b.at.getTime());
  const findings = [...(findingsQ.data ?? [])].reverse();
  const reportFor = (e: RepoEvent): Report | undefined => reports.find((r) => r.eventId === e.id);
  const running = inst.status === "running";

  // Песочницу создаёт юзер: hub зовёт OpenSandbox (no-TTL) по подключению
  // Сборки и привязывает Экземпляр; раннер только подключается по externalId.
  const sandboxAlive = inst.sandboxInstanceId != null && inst.sandboxStatus === "alive";
  const createSandbox = async () => {
    const connId = build?.sandboxConnectionId;
    if (connId == null) {
      setSandboxError("Сборка has no sandbox connection — set one on the Builds screen.");
      return;
    }
    setSandboxBusy(true);
    setSandboxError(null);
    try {
      const si = await api.createSandboxInstance({ sandboxConnectionId: connId });
      await api.setInstanceSandbox(inst.id, si.id);
      setActivity((a) => [...a, { at: new Date(), text: `sandbox created → ${si.externalId}` }]);
      instQ.reload();
    } catch (err) {
      setSandboxError(err instanceof Error ? err.message : "sandbox create failed");
    } finally {
      setSandboxBusy(false);
    }
  };
  const killSandbox = async () => {
    if (inst.sandboxInstanceId == null) return;
    setSandboxBusy(true);
    setSandboxError(null);
    try {
      await api.killSandboxInstance(inst.sandboxInstanceId);
      setActivity((a) => [...a, { at: new Date(), text: `sandbox killed → ${inst.sandboxExternalId ?? `#${inst.sandboxInstanceId}`}` }]);
      instQ.reload();
    } catch (err) {
      setSandboxError(err instanceof Error ? err.message : "sandbox kill failed");
    } finally {
      setSandboxBusy(false);
    }
  };

  const runAgent = async (mode?: "full") => {
    if (mode === "full" && !window.confirm("Full scan is a long and expensive run — start it?")) return;
    setTriggering(true);
    setTriggerError(null);
    try {
      const res = await api.triggerRepository(inst.repositoryId, mode ? { mode } : undefined);
      setActivity((a) => [
        ...a,
        { at: new Date(), text: `${mode === "full" ? "full scan" : "manual trigger"} → Событие #${res.event.id} @ ${res.event.commitSha?.slice(0, 8) ?? "HEAD"}` },
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
          <Button variant="primary" disabled={triggering} onClick={() => runAgent()}>
            {triggering ? "Triggering…" : "▶ Run agent"}
          </Button>
          <Button variant="ghost" disabled={triggering} onClick={() => runAgent("full")}>
            Full scan
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
              {inst.sandboxInstanceId != null ? (
                <>
                  <span className={`${styles.presenceDot} ${sandboxAlive ? styles.awake : styles.asleep}`} />
                  <span className={styles.mono}>{inst.sandboxExternalId ?? `#${inst.sandboxInstanceId}`}</span>
                </>
              ) : (
                "none"
              )}
            </span>
          </div>
          <div className={styles.statusItem}>
            <span className={styles.statusLabel}>updated</span>
            <span className={styles.statusValue}>
              {inst.updatedAt ? new Date(inst.updatedAt).toLocaleTimeString() : "—"}
            </span>
          </div>
        </div>

        <InstanceGraphPanel
          frames={frames}
          done={turnDone}
          live={graphEventId == null}
          turnLabel={graphEventId != null ? `Событие #${graphEventId}` : "live"}
          onBackToLive={() => setGraphEventId(null)}
        />

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
                    <div
                      key={e.id}
                      className={`${styles.tlRow} ${styles.tlClickable} ${graphEventId === e.id ? styles.tlSelected : ""}`}
                      title="показать ход этого События на графе"
                      onClick={() => setGraphEventId(graphEventId === e.id ? null : e.id)}
                    >
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
                right={<span className={styles.cell}>{log.length}</span>}
              />
              <div className={styles.activityLog}>
                {log.length === 0 && (
                  <div className={styles.panelEmpty}>
                    No activity yet for this ход. Trigger the agent (or click a Событие in the timeline) and the
                    activity stream lands here and on the graph above.
                  </div>
                )}
                {log.map((a, i) => (
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
            <Panel>
              <PanelHeader
                icon="▣"
                title="ПЕСОЧНИЦА"
                right={
                  inst.sandboxInstanceId != null ? (
                    <Badge tone={sandboxAlive ? "text" : "burnt"}>{inst.sandboxStatus ?? "?"}</Badge>
                  ) : undefined
                }
              />
              {instQ.loading && inst.sandboxInstanceId == null ? (
                <div className={styles.panelEmpty}>loading…</div>
              ) : sandboxAlive ? (
                <div className={styles.panelBody}>
                  <p className={styles.panelNote}>
                    <span className={styles.mono}>{inst.sandboxExternalId}</span> — alive, no-TTL. The
                    runner only connects to it; killing it stops Событие processing until a new one is
                    created.
                  </p>
                  <Button disabled={sandboxBusy} onClick={killSandbox}>
                    {sandboxBusy ? "Killing…" : "✕ Убить песочницу"}
                  </Button>
                </div>
              ) : (
                <div className={styles.panelBody}>
                  <p className={styles.panelNote}>
                    {inst.sandboxInstanceId != null
                      ? `Previous sandbox ${inst.sandboxExternalId ?? ""} is dead. Событиям нужна живая песочница — create a new one.`
                      : "No sandbox yet. The agent cannot process События until you create one (the runner never creates sandboxes itself)."}
                  </p>
                  <Button variant="primary" disabled={sandboxBusy} onClick={createSandbox}>
                    {sandboxBusy
                      ? "Creating…"
                      : `+ Создать песочницу${build ? ` (connection #${build.sandboxConnectionId ?? "—"})` : ""}`}
                  </Button>
                </div>
              )}
              {sandboxError && <p className={styles.error}>{sandboxError}</p>}
            </Panel>

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
