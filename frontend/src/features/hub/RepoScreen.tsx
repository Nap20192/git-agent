/** Repository page — the agents' home. N Сборок watch a repo via подписки
 *  (ticket 011: actions + ref mask; no subscriptions → the default Сборка
 *  covers everything), and each matched Сборка gets its own Экземпляр. The
 *  watchers panel doubles as the agent switcher: the selected watcher's agent
 *  backs the chat, reports, and findings. */
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useHubApi, type AgentBuild, type AgentInstance, type Finding, type Subscription } from "@/api/hub";
import {
  useBuilds,
  useHubRepositories,
  useInstanceFindings,
  useInstanceReports,
  useInstances,
  useRepoEvents,
  useSubscriptions,
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

/** "push, pull_request @ release/*" | "everything @ any ref" */
function filterLabel(s: Subscription): string {
  const actions = s.actions.length ? s.actions.join(", ") : "everything";
  return `${actions} @ ${s.refMask ?? "any ref"}`;
}

export function RepoScreen() {
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const navigate = useNavigate();
  const api = useHubApi();

  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const instancesQ = useInstances();
  const eventsQ = useRepoEvents(id);
  const subsQ = useSubscriptions(id);
  const [busy, setBusy] = useState(false);
  const [selectedBuildId, setSelectedBuildId] = useState<number | null>(null);

  const repo = (reposQ.data ?? []).find((r) => r.id === id);
  const builds = buildsQ.data ?? [];
  const events = eventsQ.data ?? [];
  const subs = subsQ.data ?? [];
  const repoInstances = (instancesQ.data ?? []).filter((i) => i.repositoryId === id);
  const buildName = (bid: number) => builds.find((b) => b.id === bid)?.name ?? `Сборка #${bid}`;
  const instanceFor = (bid: number) => repoInstances.find((i) => i.buildId === bid);

  // Active agent: the picked watcher's instance, else the awake one, else any.
  const autoInstance = repoInstances.find((i) => i.status === "running") ?? repoInstances[0];
  const activeInstance = selectedBuildId != null ? instanceFor(selectedBuildId) : autoInstance;
  const activeBuildId = selectedBuildId ?? activeInstance?.buildId ?? null;

  if (!repo) {
    return (
      <div className={styles.gate}>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          {reposQ.loading ? "loading…" : "This repository isn't connected. Pick one from the repositories page."}
        </span>
      </div>
    );
  }

  // Manual run — same path as a webhook push; jump straight to the raised
  // agent's Playground (prefer the selected watcher's Экземпляр).
  // mode "full" = full security audit of the whole repo, confirmed first.
  const runAgent = async (mode?: "full") => {
    if (mode === "full" && !window.confirm("Full scan is a long and expensive run — start it?")) return;
    setBusy(true);
    try {
      const res = await api.triggerRepository(repo!.id, mode ? { mode } : undefined);
      const target =
        res.instances.find((i) => i.buildId === activeBuildId) ?? res.instances[0];
      if (target) navigate(`/instances/${target.id}`);
      else {
        eventsQ.reload();
        instancesQ.reload();
      }
    } finally {
      setBusy(false);
    }
  };

  const putToSleep = async () => {
    if (!activeInstance) return;
    setBusy(true);
    try {
      await api.stopInstance(activeInstance.id);
      instancesQ.reload();
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
          <AgentPresence instance={activeInstance} />
          <div style={{ flex: 1 }} />
          <Button variant="primary" disabled={busy} onClick={() => runAgent()}>
            {busy ? "…" : "▶ Run agent"}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={() => runAgent("full")}>
            Full scan
          </Button>
          {activeInstance && (
            <Button variant="ghost" onClick={() => navigate(`/instances/${activeInstance.id}`)}>
              Playground →
            </Button>
          )}
          {activeInstance?.status === "running" && (
            <Button variant="ghost" disabled={busy} onClick={putToSleep}>
              Put to sleep
            </Button>
          )}
        </div>
        <p className={styles.blurb}>
          Watchers are Сборки subscribed to this repository's События — each keeps its own agent and thread of
          knowledge. Pick a watcher to read its reports or talk to its agent.
        </p>

        <div className={styles.repoGrid}>
          <InstanceChatPanel
            instanceId={activeInstance?.id ?? null}
            agentLabel={activeInstance ? buildName(activeInstance.buildId) : undefined}
            onStatusChange={instancesQ.reload}
          />

          <div className={styles.rail}>
            <WatchersPanel
              repositoryId={repo.id}
              subs={subs}
              builds={builds}
              loading={subsQ.loading}
              activeBuildId={activeBuildId}
              instanceFor={instanceFor}
              buildName={buildName}
              onSelect={setSelectedBuildId}
              reload={() => {
                subsQ.reload();
                instancesQ.reload();
              }}
            />

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

            {activeInstance && <InstancePanels instance={activeInstance} />}

            <Panel soft>
              <PanelHeader icon="✳" title="SETTINGS" />
              <div style={{ padding: "12px 14px" }}>
                <div className={styles.actions} style={{ marginTop: 0 }}>
                  <Button variant="ghost" disabled={busy} onClick={disconnect}>
                    Disconnect repository
                  </Button>
                </div>
                <p className={styles.hint}>
                  Disconnecting removes the webhook from the provider. The agents' knowledge stays in their checkpoints.
                </p>
              </div>
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── watchers (подписки) — list + add-from-builds form ──────────────── */

function WatchersPanel({
  repositoryId,
  subs,
  builds,
  loading,
  activeBuildId,
  instanceFor,
  buildName,
  onSelect,
  reload,
}: {
  repositoryId: number;
  subs: Subscription[];
  builds: AgentBuild[];
  loading: boolean;
  activeBuildId: number | null;
  instanceFor: (buildId: number) => AgentInstance | undefined;
  buildName: (buildId: number) => string;
  onSelect: (buildId: number) => void;
  reload: () => void;
}) {
  const api = useHubApi();
  const [adding, setAdding] = useState(false);
  const [buildId, setBuildId] = useState("");
  const [actions, setActions] = useState("");
  const [refMask, setRefMask] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const defaultBuild = builds.find((b) => b.isDefault);

  const submit = async () => {
    if (!buildId) return;
    setBusy(true);
    setError(null);
    try {
      await api.createSubscription(repositoryId, {
        buildId: Number(buildId),
        actions: actions
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
        refMask: refMask.trim() || null,
      });
      reload();
      setBuildId("");
      setActions("");
      setRefMask("");
      setAdding(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to add watcher");
    } finally {
      setBusy(false);
    }
  };

  const unsubscribe = async (sub: Subscription) => {
    setBusy(true);
    try {
      await api.deleteSubscription(sub.id);
      reload();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel>
      <PanelHeader
        icon="◉"
        title="WATCHERS — ПОДПИСКИ"
        right={
          <Button variant="ghost" onClick={() => setAdding((v) => !v)}>
            {adding ? "Close" : "Add watcher"}
          </Button>
        }
      />

      {subs.length === 0 && !adding && (
        <div className={styles.panelEmpty}>
          {loading
            ? "loading…"
            : `No watchers — the default Сборка${defaultBuild ? ` (${defaultBuild.name})` : ""} handles every Событие. Add one to narrow or split the coverage.`}
        </div>
      )}

      {subs.map((s) => {
        const inst = instanceFor(s.buildId);
        const active = s.buildId === activeBuildId;
        return (
          <div
            key={s.id}
            className={`${styles.watcherRow} ${active ? styles.watcherSel : ""}`}
            onClick={() => onSelect(s.buildId)}
          >
            <AgentPresence instance={inst} withLabel={false} />
            <span className={styles.watcherName}>{buildName(s.buildId)}</span>
            <span className={styles.watcherFilter}>{filterLabel(s)}</span>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                unsubscribe(s);
              }}
            >
              ✕
            </Button>
          </div>
        );
      })}

      {adding && (
        <div className={styles.watcherForm}>
          <label className={styles.label}>Сборка</label>
          <select className={styles.select} value={buildId} onChange={(e) => setBuildId(e.target.value)}>
            <option value="">— pick a build —</option>
            {builds.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
                {b.isDefault ? " (default)" : ""}
              </option>
            ))}
          </select>

          <label className={styles.label}>
            Actions <span className={styles.note}>— comma-separated, empty = everything</span>
          </label>
          <input
            className={styles.select}
            value={actions}
            onChange={(e) => setActions(e.target.value)}
            placeholder="push, pull_request"
          />

          <label className={styles.label}>
            Ref mask <span className={styles.note}>— glob over the branch/tag, empty = any</span>
          </label>
          <input
            className={styles.select}
            value={refMask}
            onChange={(e) => setRefMask(e.target.value)}
            placeholder="release/*"
          />

          {error && <p className={styles.error}>{error}</p>}
          <div className={styles.actions}>
            <Button variant="primary" disabled={busy || !buildId} onClick={submit}>
              Add watcher
            </Button>
          </div>
          <p className={styles.hint}>Adding the same Сборка again updates its filter.</p>
        </div>
      )}
    </Panel>
  );
}

/** Reports + findings of the active agent (hooks need its id). */
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

export function FindingRow({ finding: f }: { finding: Finding }) {
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
