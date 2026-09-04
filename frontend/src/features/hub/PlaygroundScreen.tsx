/** Playground — live view of one agent Экземпляр. Header (status, thread,
 *  sandbox instance, runner) + actions (stop turn / resume, raise, run agent,
 *  full scan; the sandbox instance is auto-created by the hub on run), then tabs: timeline (events + reports + activity
 *  log, build/counts/sandbox cards), agents (lead + Сабагенты folded from the
 *  activity SSE; click a timeline event to replay its ход), findings, chat,
 *  terminal. Entity lists poll at 5s;
 *  only activity streams. Chat and terminal stay mounted across tabs. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useHubApi, type RepoEvent, type Report } from "@/api/hub";
import { useBuilds, useHubRepositories, useInstance, useInstanceFindings, useInstanceReports, useInstances, useLlmConnections, useRepoEvents, useRunners, useSandboxConnections } from "@/hooks";
import { fmtTokens, foldActivity, useInstanceActivity } from "./activity.ts";
import { FindingsPanel, ReportView, type FindingsSource } from "./findings.tsx";
import { InstanceAgentsPanel } from "./InstanceAgentsPanel.tsx";
import { InstanceChatPanel } from "./InstanceChatPanel.tsx";
import { Clamp } from "./rich.tsx";
import { InstanceTerminalPanel } from "./InstanceTerminalPanel.tsx";
import { Dot, Panel, ago, sha, shortRef, toShellError, useScreenCtx, useShell } from "./ui.tsx";

const POLL_MS = 5000;
const TABS = ["timeline", "agents", "findings", "chat", "terminal"] as const;
type Tab = (typeof TABS)[number];

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

export function PlaygroundScreen() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const api = useHubApi();
  const { say, setLive, fail } = useShell();

  const instQ = useInstance(id);
  const inst = instQ.data;
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const llmQ = useLlmConnections();
  const sbxConnQ = useSandboxConnections();
  const runnersQ = useRunners();
  const instancesQ = useInstances();
  const eventsQ = useRepoEvents(inst?.repositoryId ?? null);
  const findingsQ = useInstanceFindings(id);
  const reportsQ = useInstanceReports(id);

  const [tab, setTab] = useState<Tab>("timeline");
  const [local, setLocal] = useState<Line[]>([]);
  // null = follow the live/latest ход; a Событие id pins the agents tab to its replay
  const [graphEventId, setGraphEventId] = useState<number | null>(null);
  const { frames, done: turnDone } = useInstanceActivity(id, graphEventId);
  const [busy, setBusy] = useState<string | null>(null);
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
    instQ.reload(); eventsQ.reload(); findingsQ.reload(); reportsQ.reload(); runnersQ.reload(); instancesQ.reload();
  };
  useEffect(() => {
    const t = setInterval(() => reloadRef.current(), POLL_MS);
    return () => clearInterval(t);
  }, []);

  const graph = useMemo(() => foldActivity(frames), [frames]);
  const findingsSource = useMemo<FindingsSource>(() => ({ list: (f) => api.listInstanceFindings(id, f), export: (format, f) => api.exportInstanceFindings(id, format, f) }), [api, id]);

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
  const log = (text: string) => setLocal((a) => [...a, { at: new Date(), text }]);

  const act = async (key: string, fn: () => Promise<string | void>) => {
    setBusy(key);
    try {
      const m = await fn();
      if (m) { say(m); log(m); }
      reloadRef.current();
    } catch (e) {
      fail(e, `${key} failed`);
      log(`error: ${toShellError(e, `${key} failed`).message}`);
    } finally {
      setBusy(null);
    }
  };
  const runAgent = (mode?: "full") => {
    if (mode === "full" && !window.confirm("Full scan is a long and expensive run — start it?")) return;
    act("trigger", async () => {
      const res = await api.triggerRepository(inst.repositoryId, mode ? { mode } : undefined);
      setGraphEventId(null);
      if (res.duplicate) return `already ran @ ${sha(res.commitSha)} — nothing new to do`;
      if (res.instanceIds.length === 0) throw new Error("no build serves this repository — make a build the default or subscribe one on the repository page");
      return `${mode === "full" ? "full scan" : "run"} @ ${sha(res.commitSha)} → agent #${res.instanceIds.join(", #")}`;
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
  const raise = () => act("raise", async () => { const { status } = await api.raiseInstance(inst.id); return status === "queued" ? "raise queued — runner slots busy" : `agent #${inst.id} raised`; });
  const killSandbox = () => {
    if (inst.sandboxInstanceId == null || !window.confirm("Kill this sandbox instance? The next run agent / chat creates a fresh one from the build's sandbox connection.")) return;
    act("sandbox", async () => { await api.killSandboxInstance(inst.sandboxInstanceId!); return `sandbox instance killed → ${inst.sandboxExternalId ?? `#${inst.sandboxInstanceId}`}`; });
  };

  // timeline: events (●, click → replay on graph) + reports (→) + the user's own actions here (⚙), newest first;
  // the agent's work (tool calls, subagents) lives on the agents tab, not here
  const timeline = [
    ...events.map((e) => ({ t: new Date(e.receivedAt), glyph: "●", color: graphEventId === e.id ? "var(--accent)" : "var(--text-muted)", title: e.action, meta: `${shortRef(e.ref)} @ ${sha(e.commitSha)}${reportFor(e) ? "" : running ? " · no report yet" : " · unfinished"}`, body: "", report: undefined as Report | undefined, eventId: e.id })),
    ...reports.map((r) => ({ t: new Date(r.createdAt), glyph: "→", color: "var(--accent)", title: "report", meta: `${r.action ?? ""}${r.commitSha ? ` @ ${sha(r.commitSha)}` : ""}${r.eventId != null ? ` · event #${r.eventId}` : ""}`.trim(), body: "", report: r, eventId: null })),
    ...local.map((l) => ({ t: l.at, glyph: "⚙", color: "var(--text-comment)", title: "", meta: l.text, body: "", report: undefined as Report | undefined, eventId: null })),
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
            {inst.status} · thread {inst.threadId ?? "—"} · sandbox instance {inst.sandboxExternalId ? `${inst.sandboxExternalId} (${inst.sandboxStatus})` : "none yet"} · runner {runner ? `${runner.name} ${runner.address}` : "—"} · updated {ago(inst.updatedAt)}
          </div>
        </div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          {running ? (
            <button className="btn md danger" disabled={busy != null || !turnActive} title={turnActive ? "cancel the executing turn; the event stays unfinished" : "no executing turn"} onClick={stopTurn}>
              {busy === "stop" ? "stopping…" : "■ stop turn"}
            </button>
          ) : (
            <>
              <button className="btn md" disabled={busy != null || !hasUnfinished} title={hasUnfinished ? "republish unfinished events; the turn continues from the checkpoint" : "no unfinished events"} onClick={resumeTurn}>
                {busy === "resume" ? "resuming…" : "⟳ resume"}
              </button>
              <button className="btn md" disabled={busy != null} title="load the agent from its checkpoint into a runner slot without a new event (chat does this too)" onClick={raise}>{busy === "raise" ? "raising…" : "raise agent"}</button>
            </>
          )}
          <button className="btn primary" disabled={busy != null} title={`review HEAD of ${repo?.defaultBranch ?? "the default branch"}`} onClick={() => runAgent()}>{busy === "trigger" ? "starting…" : `❯ run agent @ ${repo?.defaultBranch ?? "main"}`}</button>
          <button className="btn md" disabled={busy != null} title="full security audit of the whole repository — long and expensive" onClick={() => runAgent("full")}>full scan</button>
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
                  {it.report && <div style={{ marginTop: 4 }}><Clamp lines={10}><ReportView report={it.report} /></Clamp></div>}
                </div>
              </div>
            ))}
            {timeline.length === 0 && <div className="empty">{eventsQ.loading && eventsQ.data === undefined ? "loading…" : "no events yet — press run agent (or push to the repo if it has a webhook)."}</div>}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <Panel label="build" className="elev pad">
              <div><b>{build?.name ?? "—"}</b></div>
              <div className="small comment pretty" style={{ marginTop: 4 }}>{build?.prompt || "no prompt — runs the reviewer default"}</div>
              <div className="small muted" style={{ marginTop: 6 }}>
                llm {(llmQ.data ?? []).find((c) => c.id === build?.llmConnectionId)?.name ?? "—"}<br />
                sandbox connection {(sbxConnQ.data ?? []).find((c) => c.id === build?.sandboxConnectionId)?.name ?? "—"}<br />
                memory {build?.memoryPreset ?? "—"} · {limitsText(build?.limits)}
              </div>
            </Panel>
            <Panel label="counts" className="elev pad">
              <div className="kv"><span>reports</span><span>{reports.length}</span></div>
              <div className="kv"><span>findings</span><span>{findings.length}</span></div>
              <div className="kv"><span>subagents</span><span className="comment">{saList.length} spawned · {saRunning} running</span></div>
              <div className="kv"><span>tokens</span><span className="comment" title={`${graph.tokens.input.toLocaleString()} in · ${graph.tokens.output.toLocaleString()} out · lead ${fmtTokens(graph.leadTokens.input + graph.leadTokens.output)}`}>{graph.tokens.input || graph.tokens.output ? `${fmtTokens(graph.tokens.input + graph.tokens.output)} · ${fmtTokens(graph.tokens.input)} in · ${fmtTokens(graph.tokens.output)} out` : "—"}</span></div>
            </Panel>
            <Panel label="sandbox instance" dim="auto-created on run" className="elev pad">
              {sandboxAlive ? (
                <>
                  <div className="small comment pretty"><b>{inst.sandboxExternalId}</b> — alive, no ttl. this agent's own container; the runner connects to it on every turn. kill it if it went stale — the next run creates a fresh one.</div>
                  <button className="btn danger" style={{ marginTop: 8 }} disabled={busy != null} onClick={killSandbox}>{busy === "sandbox" ? "killing…" : "✕ kill sandbox instance"}</button>
                </>
              ) : (
                <div className="small comment pretty">
                  {inst.sandboxInstanceId != null ? `previous instance ${inst.sandboxExternalId ?? ""} is dead — the next run agent / chat creates a fresh one` : "none yet — the first run agent / chat creates one"} from the build's sandbox connection.
                </div>
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

      {tab === "findings" && <FindingsPanel source={findingsSource} events={events} empty="no findings filed by this agent yet." fileName={`findings-${repo ? `${repo.owner}-${repo.name}` : `instance-${inst.id}`}`} />}

      <div className="box" hidden={tab !== "chat"} style={{ display: tab === "chat" ? "flex" : undefined, flexDirection: "column", flex: 1, minHeight: 420 }}>
        <InstanceChatPanel instanceId={inst.id} empty={`thread ${inst.threadId ?? "—"} · nothing said yet.`} onStatusChange={() => { instQ.reload(); instancesQ.reload(); }} onActivity={log} />
      </div>

      <div hidden={tab !== "terminal"} style={{ display: tab === "terminal" ? "flex" : undefined, flexDirection: "column", flex: 1, minHeight: 0 }}>
        <InstanceTerminalPanel instanceId={inst.id} running={running} hasSandbox={sandboxAlive} sandboxLabel={inst.sandboxExternalId ?? "none"} />
      </div>
    </div>
  );
}
