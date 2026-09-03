/** Playground — live view of one agent Экземпляр. Header (status, thread,
 *  sandbox, runner) + actions (attach sandbox, stop turn / resume, raise,
 *  run agent, full scan), then tabs: timeline (events + reports + activity
 *  log, build/counts/sandbox cards), agents (lead + Сабагенты folded from the
 *  activity SSE; click a timeline event to replay its ход), findings, chat,
 *  terminal. Entity lists poll at 5s;
 *  only activity streams. Chat and terminal stay mounted across tabs. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useHubApi, type Finding, type RepoEvent, type Report } from "@/api/hub";
import { useBuilds, useHubRepositories, useInstance, useInstanceFindings, useInstanceReports, useInstances, useLlmConnections, useRepoEvents, useRunners, useSandboxConnections, useSandboxInstancesHub } from "@/hooks";
import { activityLine, foldActivity, useInstanceActivity } from "./activity.ts";
import { InstanceAgentsPanel } from "./InstanceAgentsPanel.tsx";
import { InstanceChatPanel } from "./InstanceChatPanel.tsx";
import { Clamp, Rich } from "./rich.tsx";
import { InstanceTerminalPanel } from "./InstanceTerminalPanel.tsx";
import { Dot, Panel, ago, errMsg, sha, shortRef, useScreenCtx, useShell } from "./ui.tsx";

const POLL_MS = 5000;
const TABS = ["timeline", "agents", "findings", "chat", "terminal"] as const;
type Tab = (typeof TABS)[number];
const FCOLS = "70px 100px 1.2fr 1.4fr 1.4fr";
const SEV_COLOR: Record<string, string> = { critical: "var(--error)", crit: "var(--error)", high: "var(--error)", medium: "var(--warning)", med: "var(--warning)", low: "var(--text-muted)" };

interface Line {
  at: Date;
  text: string;
}

/** Known limits keys (agent/core/lead/graph.py::_lead_features). */
export function limitsText(limits?: Record<string, unknown>): string {
  const n = (k: string) => (typeof limits?.[k] === "number" ? (limits[k] as number) : null);
  const p: string[] = [];
  const conc = n("maxSubagents"); if (conc != null) p.push(`${conc} subagents`);
  const tot = n("maxTotalSubagents"); if (tot != null) p.push(`${tot} total`);
  const st = n("subagentTimeout"); if (st != null) p.push(`${st}s timeout`);
  const qt = n("queueTimeout"); if (qt != null) p.push(`${qt}s queue`);
  const b = n("tokenBudget"); if (b != null) p.push(`${b.toLocaleString("en-US")} tokens`);
  return p.length ? p.join(" · ") : "no limits";
}

export function FindingsTable({ rows, loading }: { rows: Finding[]; loading?: boolean }) {
  const loc = (f: Finding) => (f.file ? `${f.file}${f.lineStart != null ? `:${f.lineStart}${f.lineEnd != null && f.lineEnd !== f.lineStart ? `-${f.lineEnd}` : ""}` : ""}` : "—");
  return (
    <div className="box">
      <div className="thead" style={{ "--cols": FCOLS } as React.CSSProperties}>
        <span>severity</span><span>cwe</span><span>location</span><span>evidence</span><span>remediation</span>
      </div>
      {rows.map((f) => (
        <div key={f.id} className="trow top" style={{ "--cols": FCOLS } as React.CSSProperties}>
          <span style={{ fontWeight: 700, color: SEV_COLOR[f.severity.toLowerCase()] ?? "var(--text)" }}>{f.severity}</span>
          <span className="comment">{f.cwe ?? f.cve ?? "—"}</span>
          <span style={{ textDecoration: "underline", wordBreak: "break-all" }}>{loc(f)}</span>
          <span className="comment"><Clamp lines={6}><Rich>{f.evidence ?? ""}</Rich></Clamp></span>
          <span><Clamp lines={6}><Rich>{f.remediation ?? ""}</Rich></Clamp></span>
        </div>
      ))}
      {rows.length === 0 && <div className="empty">{loading ? "loading…" : "no findings filed by this instance."}</div>}
    </div>
  );
}

export function PlaygroundScreen() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const api = useHubApi();
  const { say, setLive } = useShell();

  const instQ = useInstance(id);
  const inst = instQ.data;
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const llmQ = useLlmConnections();
  const sbxConnQ = useSandboxConnections();
  const runnersQ = useRunners();
  const instancesQ = useInstances();
  const sbxQ = useSandboxInstancesHub();
  const eventsQ = useRepoEvents(inst?.repositoryId ?? null);
  const findingsQ = useInstanceFindings(id);
  const reportsQ = useInstanceReports(id);

  const [tab, setTab] = useState<Tab>("timeline");
  const [local, setLocal] = useState<Line[]>([]);
  // null = follow the live/latest ход; a Событие id pins the agents tab to its replay
  const [graphEventId, setGraphEventId] = useState<number | null>(null);
  const { frames, done: turnDone } = useInstanceActivity(id, graphEventId);
  const [busy, setBusy] = useState<string | null>(null);
  const [attach, setAttach] = useState("");
  const [saSel, setSaSel] = useState<string | null>(null);

  const repo = (reposQ.data ?? []).find((r) => r.id === inst?.repositoryId);
  const build = (buildsQ.data ?? []).find((b) => b.id === inst?.buildId);
  useScreenCtx(repo && inst ? `${repo.owner}/${repo.name} · #${inst.id}` : null);
  useEffect(() => {
    setLive(graphEventId == null && frames.length > 0 && !turnDone);
    return () => setLive(false);
  }, [graphEventId, frames.length, turnDone, setLive]);

  // Poll everything the screen shows; reload identities change per render, so read through a ref.
  const reloadRef = useRef(() => {});
  reloadRef.current = () => {
    instQ.reload(); eventsQ.reload(); findingsQ.reload(); reportsQ.reload(); runnersQ.reload(); instancesQ.reload(); sbxQ.reload();
  };
  useEffect(() => {
    const t = setInterval(() => reloadRef.current(), POLL_MS);
    return () => clearInterval(t);
  }, []);

  const graph = useMemo(() => foldActivity(frames), [frames]);

  if (instQ.error || (inst == null && !instQ.loading)) {
    return <div className="gate">{instQ.error ? `failed to load instance #${id}: ${instQ.error.message}` : `instance #${id} not found.`}</div>;
  }
  if (inst == null) return <div className="gate">loading…</div>;

  const runner = inst.runnerId != null ? (runnersQ.data ?? []).find((r) => r.id === inst.runnerId) : undefined;
  const events = eventsQ.data ?? [];
  const reports = reportsQ.data ?? [];
  const findings = findingsQ.data ?? [];
  const running = inst.status === "running";
  const reportFor = (e: RepoEvent): Report | undefined => reports.find((r) => r.eventId === e.id);
  // honest button states: stop only an executing live turn; resume only with an unreported Событие
  const turnActive = graphEventId == null && frames.length > 0 && !turnDone;
  const hasUnfinished = events.some((e) => !reportFor(e));
  const sandboxAlive = inst.sandboxInstanceId != null && inst.sandboxStatus === "alive";
  const aliveSandboxes = (sbxQ.data ?? []).filter((s) => s.status === "alive");
  const log = (text: string) => setLocal((a) => [...a, { at: new Date(), text }]);

  const act = async (key: string, fn: () => Promise<string | void>) => {
    setBusy(key);
    try {
      const m = await fn();
      if (m) { say(m); log(m); }
      reloadRef.current();
    } catch (e) {
      const m = errMsg(e, `${key} failed`);
      say(m);
      log(`error: ${m}`);
    } finally {
      setBusy(null);
    }
  };
  const runAgent = (mode?: "full") => {
    if (mode === "full" && !window.confirm("Full scan is a long and expensive run — start it?")) return;
    act("trigger", async () => {
      const res = await api.triggerRepository(inst.repositoryId, mode ? { mode } : undefined);
      setGraphEventId(null);
      return `${mode === "full" ? "full scan" : "manual trigger"} → event #${res.event.id} @ ${sha(res.event.commitSha)}`;
    });
  };
  // «Остановить ход»: the runner cancels the executing turn; the Событие stays unprocessed → «Продолжить» resumes from the checkpoint.
  const stopTurn = () => {
    if (!window.confirm("Stop the executing turn? The event stays unfinished — it can be resumed from the checkpoint.")) return;
    act("stop", async () => { await api.stopInstance(inst.id); return "turn stopped — instance down, event can be resumed"; });
  };
  // «Продолжить»: republish unfinished События + fast raise (queued = waiting for a runner slot).
  const resumeTurn = () =>
    act("resume", async () => {
      const { eventIds } = await api.resumeInstance(inst.id);
      if (eventIds.length === 0) return "nothing to resume — no unfinished events";
      const { status } = await api.raiseInstance(inst.id);
      setGraphEventId(null);
      return status === "queued" ? `resume: event #${eventIds.join(", #")} re-queued; instance waits for a runner slot` : `resume: event #${eventIds.join(", #")} continues from the checkpoint`;
    });
  const raise = () => act("raise", async () => { const { status } = await api.raiseInstance(inst.id); return status === "queued" ? "raise queued — runner slots busy" : `instance #${inst.id} raised`; });
  const attachSandbox = () => {
    const sid = Number(attach);
    if (!sid) return say("pick a sandbox first");
    act("attach", async () => { await api.setInstanceSandbox(inst.id, sid); setAttach(""); return `sandbox attached to instance #${inst.id}`; });
  };
  const createSandbox = () => {
    const connId = build?.sandboxConnectionId;
    if (connId == null) return say("build has no sandbox connection — set one on the builds page.");
    act("sandbox", async () => {
      const si = await api.createSandboxInstance({ sandboxConnectionId: connId });
      await api.setInstanceSandbox(inst.id, si.id);
      return `sandbox created → ${si.externalId}`;
    });
  };
  const killSandbox = () => {
    if (inst.sandboxInstanceId == null) return;
    act("sandbox", async () => { await api.killSandboxInstance(inst.sandboxInstanceId!); return `sandbox killed → ${inst.sandboxExternalId ?? `#${inst.sandboxInstanceId}`}`; });
  };

  // timeline: events (●, click → replay on graph) + reports (→) + activity lines (⚙; node frames stay on the graph), newest first
  const timeline = [
    ...events.map((e) => ({ t: new Date(e.receivedAt), glyph: "●", color: graphEventId === e.id ? "var(--accent)" : "var(--text-muted)", title: e.action, meta: `${shortRef(e.ref)} @ ${sha(e.commitSha)}${reportFor(e) ? "" : running ? " · no report yet" : " · unfinished"}`, body: "", eventId: e.id })),
    ...reports.map((r) => ({ t: new Date(r.createdAt), glyph: "→", color: "var(--accent)", title: "report", meta: r.eventId != null ? `for event #${r.eventId}` : "", body: r.summary, eventId: null })),
    ...[...local, ...frames.filter((f) => f.kind !== "node").flatMap((f) => { const text = activityLine(f); return text ? [{ at: f.ts ? new Date(f.ts) : new Date(), text }] : []; })].map((l) => ({ t: l.at, glyph: "⚙", color: "var(--text-comment)", title: "", meta: l.text, body: "", eventId: null })),
  ].sort((a, b) => b.t.getTime() - a.t.getTime());

  const saList = graph.tasks;
  const saRunning = saList.filter((x) => x.status === "working").length;
  const turnReport = graphEventId != null ? reports.find((r) => r.eventId === graphEventId) : reports[0];
  const tabLabel = (t: Tab) => (t === "findings" && findings.length ? `findings ${findings.length}` : t === "agents" && saRunning ? `agents ● ${saRunning}` : t);

  return (
    <div className="screen">
      <div className="head">
        <div>
          <div className="crumbs">
            <a href="/repos" onClick={(e) => { e.preventDefault(); navigate("/repos"); }}>repositories</a> →{" "}
            <a href={repo ? `/repos/${repo.id}` : "/repos"} onClick={(e) => { e.preventDefault(); navigate(repo ? `/repos/${repo.id}` : "/repos"); }}>{repo ? `${repo.owner}/${repo.name}` : "…"}</a> → playground
          </div>
          <h1 style={{ marginTop: 4 }}>
            <Dot on={running} pulse={running} />{build?.name ?? "instance"} <span className="muted" style={{ fontWeight: 400 }}>#{inst.id}</span>
          </h1>
          <div className="sub comment">
            {inst.status} · thread {inst.threadId ?? "—"} · sandbox {inst.sandboxExternalId ? `${inst.sandboxExternalId} (${inst.sandboxStatus})` : "none"} · runner {runner ? `${runner.name} ${runner.address}` : "—"} · updated {ago(inst.updatedAt)}
          </div>
        </div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          {!sandboxAlive && aliveSandboxes.length > 0 && (
            <>
              <select className="select" value={attach} onChange={(e) => setAttach(e.target.value)}>
                <option value="">attach sandbox…</option>
                {aliveSandboxes.map((s) => (<option key={s.id} value={s.id}>{s.externalId}</option>))}
              </select>
              <button className="btn md" disabled={busy != null} onClick={attachSandbox}>attach</button>
            </>
          )}
          {running ? (
            <button className="btn md danger" disabled={busy != null || !turnActive} title={turnActive ? "cancel the executing turn; the event stays unfinished" : "no executing turn"} onClick={stopTurn}>
              {busy === "stop" ? "stopping…" : "■ stop turn"}
            </button>
          ) : (
            <>
              <button className="btn md" disabled={busy != null || !hasUnfinished} title={hasUnfinished ? "republish unfinished events; the turn continues from the checkpoint" : "no unfinished events"} onClick={resumeTurn}>
                {busy === "resume" ? "resuming…" : "⟳ resume"}
              </button>
              <button className="btn md" disabled={busy != null} onClick={raise}>{busy === "raise" ? "raising…" : "raise instance"}</button>
            </>
          )}
          <button className="btn primary" disabled={busy != null} onClick={() => runAgent()}>{busy === "trigger" ? "triggering…" : "❯ run agent"}</button>
          <button className="btn md" disabled={busy != null} onClick={() => runAgent("full")}>full scan</button>
        </div>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={`tab${tab === t ? " active" : ""}`} onClick={() => setTab(t)}>{tabLabel(t)}</button>
        ))}
      </div>

      {tab === "timeline" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 16, flex: 1, minHeight: 0 }}>
          <div className="box" style={{ overflow: "auto" }}>
            {timeline.map((it, i) => (
              <div
                key={i}
                style={{ display: "grid", gridTemplateColumns: "120px 3ch 1fr", padding: "8px 12px", borderBottom: "1px solid var(--border)", alignItems: "baseline", cursor: it.eventId != null ? "pointer" : undefined, background: it.eventId != null && it.eventId === graphEventId ? "var(--bg-cursorline)" : undefined }}
                title={it.eventId != null ? "show this event's turn on the agents tab" : undefined}
                onClick={it.eventId != null ? () => { setGraphEventId(graphEventId === it.eventId ? null : it.eventId); setTab("agents"); } : undefined}
              >
                <span className="small muted">{ago(it.t.toISOString())}</span>
                <span style={{ color: it.color }}>{it.glyph}</span>
                <div style={{ minWidth: 0 }}>
                  {it.title && <span style={{ fontWeight: 700 }}>{it.title} </span>}
                  <span className="comment">{it.meta}</span>
                  {it.body && <div style={{ marginTop: 4 }}><Clamp lines={6}><Rich>{it.body}</Rich></Clamp></div>}
                </div>
              </div>
            ))}
            {timeline.length === 0 && <div className="empty">{eventsQ.loading && eventsQ.data === undefined ? "loading…" : "no events yet — trigger a run or push to the repo."}</div>}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <Panel label="build" className="elev pad">
              <div><b>{build?.name ?? "—"}</b>{build?.isDefault && <span className="muted"> · default</span>}</div>
              <div className="small comment pretty" style={{ marginTop: 4 }}>{build?.prompt || "no prompt — runs the reviewer default"}</div>
              <div className="small muted" style={{ marginTop: 6 }}>
                llm {(llmQ.data ?? []).find((c) => c.id === build?.llmConnectionId)?.name ?? "—"}<br />
                sandbox {(sbxConnQ.data ?? []).find((c) => c.id === build?.sandboxConnectionId)?.name ?? "—"}<br />
                memory {build?.memoryPreset ?? "—"} · {limitsText(build?.limits)}
              </div>
            </Panel>
            <Panel label="counts" className="elev pad">
              <div className="kv"><span>reports</span><span>{reports.length}</span></div>
              <div className="kv"><span>findings</span><span>{findings.length}</span></div>
              <div className="kv"><span>subagents</span><span className="comment">{saList.length} spawned · {saRunning} running</span></div>
            </Panel>
            <Panel label="sandbox" dim={inst.sandboxInstanceId != null ? inst.sandboxStatus ?? "?" : "none"} className="elev pad">
              {sandboxAlive ? (
                <>
                  <div className="small comment pretty"><b>{inst.sandboxExternalId}</b> — alive, no ttl. the runner only connects to it; killing it stops event processing until a new one is created.</div>
                  <button className="btn danger" style={{ marginTop: 8 }} disabled={busy != null} onClick={killSandbox}>{busy === "sandbox" ? "killing…" : "✕ kill sandbox"}</button>
                </>
              ) : (
                <>
                  <div className="small comment pretty">
                    {inst.sandboxInstanceId != null ? `previous sandbox ${inst.sandboxExternalId ?? ""} is dead. events need a live sandbox — create a new one.` : "no sandbox yet. the agent cannot process events until you create one (the runner never creates sandboxes itself)."}
                  </div>
                  <button className="btn primary" style={{ marginTop: 8 }} disabled={busy != null} onClick={createSandbox}>{busy === "sandbox" ? "creating…" : `+ create sandbox${build?.sandboxConnectionId != null ? ` · connection #${build.sandboxConnectionId}` : ""}`}</button>
                </>
              )}
            </Panel>
          </div>
        </div>
      )}

      {tab === "agents" && (
        <>
          <div className="small muted" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {graphEventId == null ? (
              <span>{turnActive ? <span className="accent pulse">● live turn</span> : "last turn"}</span>
            ) : (
              <>
                <span className="accent">event #{graphEventId}</span>
                <button className="btn xs" onClick={() => setGraphEventId(null)}>→ live</button>
              </>
            )}
          </div>
          <InstanceAgentsPanel
            graph={graph}
            leadName={build?.name ?? "instance"}
            report={turnReport}
            selected={saSel}
            onSelect={setSaSel}
            footer={`${saList.length} spawned · ${saRunning} running · ${saList.filter((x) => x.status === "done").length} done · ${saList.filter((x) => x.status === "failed" || x.status === "timeout").length} failed · ${limitsText(build?.limits)}`}
          />
        </>
      )}

      {tab === "findings" && <FindingsTable rows={[...findings].reverse()} loading={findingsQ.loading && findingsQ.data === undefined} />}

      <div className="box" hidden={tab !== "chat"} style={{ display: tab === "chat" ? "flex" : undefined, flexDirection: "column", flex: 1, minHeight: 420 }}>
        <InstanceChatPanel instanceId={inst.id} empty={`thread ${inst.threadId ?? "—"} · nothing said yet.`} onStatusChange={() => { instQ.reload(); instancesQ.reload(); }} onActivity={log} />
      </div>

      <div hidden={tab !== "terminal"} style={{ display: tab === "terminal" ? "flex" : undefined, flexDirection: "column", flex: 1, minHeight: 0 }}>
        <InstanceTerminalPanel instanceId={inst.id} running={running} hasSandbox={sandboxAlive} sandboxLabel={inst.sandboxExternalId ?? "none"} />
      </div>
    </div>
  );
}
