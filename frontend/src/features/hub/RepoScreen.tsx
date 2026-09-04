/** Repository page. Watchers = the repo's Экземпляры (one per subscribed
 *  Сборка; no subscriptions → the default Сборка covers everything) with
 *  playground/stop/unsubscribe, a subscribe form (build + actions + ref mask),
 *  the Событие journal and a chat with the active watcher. */
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useHubApi, type Subscription } from "@/api/hub";
import { useBuilds, useHubRepositories, useInstances, useRepoEvents, useRepositoryReports, useSubscriptions } from "@/hooks";
import { FindingsPanel, ReportView, type FindingsSource } from "./findings.tsx";
import { InstanceChatPanel } from "./InstanceChatPanel.tsx";
import { Dot, Panel, ago, sha, shortRef, useScreenCtx, useShell } from "./ui.tsx";

const JCOLS = "150px 1fr 110px 1fr";

const subText = (sub: Subscription | undefined) =>
  sub
    ? `subscribed: ${sub.actions.length ? sub.actions.join(", ") : "all actions"} · ${sub.refMask ?? "any ref"}`
    : "no subscription · idle — events go to the subscribed builds only; subscribe this build to serve it again";

export function RepoScreen() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const api = useHubApi();
  const { say, fail } = useShell();
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const instancesQ = useInstances();
  const eventsQ = useRepoEvents(id);
  const subsQ = useSubscriptions(id);
  const reportsQ = useRepositoryReports(id);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ build: "", actions: "", ref: "" });
  const findingsSource = useMemo<FindingsSource>(() => ({ list: (x) => api.listRepositoryFindings(id, x), export: (format, x) => api.exportRepositoryFindings(id, format, x) }), [api, id]);

  const repo = (reposQ.data ?? []).find((r) => r.id === id);
  useScreenCtx(repo ? `${repo.owner}/${repo.name}` : null);
  const builds = buildsQ.data ?? [];
  const events = eventsQ.data ?? [];
  const subs = subsQ.data ?? [];
  const reports = reportsQ.data ?? [];
  const eventOf = (eid?: number | null) => events.find((e) => e.id === eid);
  const mine = (instancesQ.data ?? []).filter((i) => i.repositoryId === id);
  const buildName = (bid: number) => builds.find((b) => b.id === bid)?.name ?? `build #${bid}`;
  const subFor = (bid: number) => subs.find((s) => s.buildId === bid);
  // chat target: the running watcher, else any
  const chatInst = mine.find((i) => i.status === "running") ?? mine[0];
  // subscriptions whose Сборка has no Экземпляр yet (raised on the first Событие)
  const pending = subs.filter((s) => !mine.some((i) => i.buildId === s.buildId));
  // who answers an event here: subscribed builds only; nobody = nothing runs (there is no default build)
  const served = subs.length > 0;
  const canRun = !buildsQ.loading && !subsQ.loading && served;
  const branch = repo?.defaultBranch ?? "main";

  if (!repo) return <div className="gate">{reposQ.loading ? "loading…" : "this repository isn't connected."}</div>;

  const run = async (mode?: "full") => {
    if (mode === "full" && !window.confirm("Full scan is a long and expensive run — start it?")) return;
    setBusy(true);
    try {
      const res = await api.triggerRepository(repo.id, mode ? { mode } : undefined);
      if (res.duplicate) {
        say(`already ran @ ${sha(res.commitSha)} — nothing new to do; full scan re-runs the same commit`);
        return;
      }
      if (res.instanceIds.length === 0) {
        fail(new Error("no build serves this repository — make a build the default or subscribe one below"), "nothing to run");
        return;
      }
      say(`${mode === "full" ? "full scan" : "run"} @ ${sha(res.commitSha)} → agent #${res.instanceIds.join(", #")}`);
      const target = res.instanceIds.find((id) => id === chatInst?.id) ?? res.instanceIds[0];
      if (target !== undefined) navigate(`/instances/${target}`);
      else {
        eventsQ.reload();
        instancesQ.reload();
      }
    } catch (e) {
      fail(e, "run failed");
    } finally {
      setBusy(false);
    }
  };
  const act = async (fn: () => Promise<void>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      if (ok) say(ok);
    } catch (e) {
      fail(e, "failed");
    } finally {
      setBusy(false);
    }
  };
  // raise without a scan: no Событие, no turn — the agent just comes up on a runner (chat/terminal work right away)
  const raiseAll = () => act(async () => {
    const { instances: raised } = await api.raiseRepository(repo.id);
    instancesQ.reload();
    if (raised.length === 0) throw new Error("no build serves this repository — make a build the default or subscribe one below");
    say(raised.map((x) => `agent #${x.id} ${x.status === "queued" ? "queued for a slot" : "raised"}`).join(" · "));
  }, "");
  const raiseOne = (instId: number) => act(async () => { const { status } = await api.raiseInstance(instId); instancesQ.reload(); say(status === "queued" ? `agent #${instId} queued for a slot` : `agent #${instId} raised`); }, "");
  const stop = (instId: number) => act(async () => { await api.stopInstance(instId); instancesQ.reload(); }, `instance #${instId} stopped`);
  const unsub = (s: Subscription) => act(async () => { await api.deleteSubscription(s.id); subsQ.reload(); }, `unsubscribed ${buildName(s.buildId)}`);
  const disconnect = () => {
    const watch = repo.mode === "watch";
    if (!window.confirm(`Disconnect ${repo.owner}/${repo.name}? ${watch ? "Nothing to remove upstream (watch mode)" : "The webhook is removed"}; agents' knowledge stays in their checkpoints.`)) return;
    act(async () => { await api.disconnectRepository(repo.id); navigate("/repos"); }, `disconnected ${repo.name}${watch ? "" : " · webhook removed"}`);
  };
  const addSub = () => {
    const buildId = Number(f.build || builds[0]?.id);
    if (!buildId) return say("no build to subscribe");
    act(async () => {
      await api.createSubscription(repo.id, {
        buildId,
        actions: f.actions.split(",").map((x) => x.trim()).filter(Boolean),
        refMask: f.ref.trim() || null,
      });
      setF({ build: "", actions: "", ref: "" });
      subsQ.reload();
      instancesQ.reload();
    }, `subscribed ${buildName(buildId)} · same build again updates its filter`);
  };

  return (
    <div className="screen">
      <div className="head">
        <div>
          <div className="crumbs">
            <a href="/repos" onClick={(e) => { e.preventDefault(); navigate("/repos"); }}>repositories</a> → {repo.provider}
          </div>
          <h1 style={{ marginTop: 4 }}>
            <span className="muted" style={{ fontWeight: 400 }}>{repo.owner}/</span>{repo.name}
          </h1>
          <div className="sub comment">
            {repo.defaultBranch ?? "main"} · connected {ago(repo.connectedAt)} ·{" "}
            {repo.mode === "watch" ? <><span className="tag" title="no webhook — run manually">watch</span> no webhook — run manually</> : "webhook installed"}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
          <div className="row">
            <button className="btn primary" disabled={busy || !canRun} title={canRun ? `review HEAD of ${branch}; the hub creates the sandbox instance and the runner picks it up` : "no build serves this repository"} onClick={() => run()}>❯ run agent @ {branch}</button>
            <button className="btn md" disabled={busy || !canRun} title="bring the agent up on a runner without a scan — chat and terminal work right away, nothing is reviewed" onClick={raiseAll}>raise agent</button>
            <button className="btn md" disabled={busy || !canRun} title="full security audit of the whole repository — long and expensive" onClick={() => run("full")}>full scan</button>
            <button className="btn md danger" disabled={busy} onClick={disconnect}>disconnect</button>
          </div>
          {!served && !buildsQ.loading && !subsQ.loading && (
            <div className="small err pretty">
              {builds.length === 0 ? <>no builds yet — <a href="/builds" onClick={(e) => { e.preventDefault(); navigate("/builds"); }}>create a build</a> (llm connection + sandbox connection), then subscribe it below.</> : <>no subscription — nothing runs here until you subscribe a build below.</>}
            </div>
          )}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 16, alignItems: "stretch" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20, minWidth: 0 }}>
          <Panel label="agents" dim={mine.length + pending.length ? `${mine.length + pending.length} · one per build` : "none yet"}>
            {mine.map((w) => {
              const running = w.status === "running";
              const sub = subFor(w.buildId);
              return (
                <div key={w.id} className="lrow" style={{ padding: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <div>
                      <Dot on={running} pulse={running} />
                      <b>{buildName(w.buildId)}</b> <span className="muted">#{w.id} · {w.status}</span>
                    </div>
                    <div className="small comment" style={{ marginTop: 2 }}>
                      sandbox instance {w.sandboxExternalId ?? "none yet — created on run"}{w.sandboxStatus ? ` (${w.sandboxStatus})` : ""} · runner {w.runnerId ?? "—"} · updated {ago(w.updatedAt)}
                    </div>
                    <div className="small muted" style={{ marginTop: 2 }}>{subText(sub)}</div>
                  </div>
                  <div className="row" style={{ flexWrap: "nowrap" }}>
                    <button className="btn" onClick={() => navigate(`/instances/${w.id}`)}>playground →</button>
                    {running ? <button className="btn" disabled={busy} onClick={() => stop(w.id)}>stop</button> : <button className="btn" disabled={busy} title="bring this agent up without a scan" onClick={() => raiseOne(w.id)}>raise</button>}
                    {sub && <button className="btn danger" disabled={busy} onClick={() => unsub(sub)}>unsubscribe</button>}
                  </div>
                </div>
              );
            })}
            {pending.map((s) => (
              <div key={`s${s.id}`} className="lrow" style={{ padding: 12 }}>
                <div>
                  <div><Dot on={false} /><b>{buildName(s.buildId)}</b> <span className="muted">· not raised yet</span></div>
                  <div className="small muted" style={{ marginTop: 2 }}>{subText(s, true)} · instance appears on the first matching event</div>
                </div>
                <button className="btn danger" disabled={busy} onClick={() => unsub(s)}>unsubscribe</button>
              </div>
            ))}
            {mine.length + pending.length === 0 && (
              <div className="empty small pretty">
                {instancesQ.loading ? "loading…" : served ? <>no agent yet — the subscribed build answers the first event; press <b>run agent</b> or <b>raise agent</b> to bring it up now.</> : "no build is subscribed to this repository — nothing will run until you subscribe one below."}
              </div>
            )}
            <div className="row" style={{ padding: 12, background: "var(--bg-elevated)" }}>
              <span className="small muted">subscribe build</span>
              <select className="select" value={f.build} onChange={(e) => setF({ ...f, build: e.target.value })}>
                {builds.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
              <input className="input" style={{ flex: 1, minWidth: 180 }} value={f.actions} onChange={(e) => setF({ ...f, actions: e.target.value })} placeholder="actions · push, pull_request.opened · empty = all" />
              <input className="input" style={{ width: 160 }} value={f.ref} onChange={(e) => setF({ ...f, ref: e.target.value })} placeholder="ref mask · release/*" />
              <button className="btn" disabled={busy || builds.length === 0} onClick={addSub}>+ add</button>
            </div>
          </Panel>

          <Panel label="journal" dim={`${events.length} events`} className="col" style={{ flex: 1, minHeight: 160 }}>
            <div className="thead" style={{ "--cols": JCOLS, background: "transparent", padding: "10px 12px 6px" } as React.CSSProperties}>
              <span>action</span><span>ref</span><span>commit</span><span>received</span>
            </div>
            <div style={{ overflow: "auto", flex: 1, minHeight: 120 }}>
              {events.map((e) => (
                <div key={e.id} className="trow tight" style={{ "--cols": JCOLS } as React.CSSProperties}>
                  <span><b>{e.action}</b></span>
                  <span className="comment ellip">{shortRef(e.ref)}</span>
                  <span className="comment">{sha(e.commitSha)}</span>
                  <span className="muted">{ago(e.receivedAt)}</span>
                </div>
              ))}
              {events.length === 0 && <div className="empty small">{eventsQ.loading ? "loading…" : repo.mode === "watch" ? "nothing yet — no webhook on a watch repo: press run agent (or full scan) and the event appears here." : "nothing yet — push to the repository (the webhook delivers it) or press run agent."}</div>}
            </div>
          </Panel>
        </div>

        <Panel label="chat" dim={chatInst ? `${buildName(chatInst.buildId)} #${chatInst.id}` : "no agent yet"} className="col elev" >
          <div style={{ display: "flex", flexDirection: "column", minHeight: 420, maxHeight: "70vh", flex: 1 }}>
            <InstanceChatPanel
              instanceId={chatInst?.id ?? null}
              empty="ask the agent what it has accumulated on this repo. a down agent wakes on the first message."
              onStatusChange={instancesQ.reload}
            />
          </div>
        </Panel>
      </div>

      <Panel label="reports" dim={reports.length ? `${reports.length} · by commit` : "none yet"}>
        {reports.map((r) => {
          const e = eventOf(r.eventId);
          const inst = mine.find((i) => i.id === r.instanceId);
          return (
            <details key={r.id} className="lrow" style={{ padding: "8px 12px", display: "block" }}>
              <summary style={{ cursor: "pointer", display: "grid", gridTemplateColumns: JCOLS, gap: 8, alignItems: "baseline" }}>
                <span><b>{r.action ?? e?.action ?? "report"}</b></span>
                <span className="comment ellip">{shortRef(r.ref ?? e?.ref)}{inst ? ` · ${buildName(inst.buildId)} #${inst.id}` : ""}</span>
                <span className="comment" title={r.commitSha ?? e?.commitSha ?? undefined}>{sha(r.commitSha ?? e?.commitSha)}</span>
                <span className="muted">{ago(r.createdAt)}</span>
              </summary>
              <div style={{ marginTop: 8 }}><ReportView report={r} /></div>
            </details>
          );
        })}
        {reports.length === 0 && <div className="empty small" style={{ padding: 12 }}>{reportsQ.loading ? "loading…" : "no reports yet — the agent writes one at the end of each run."}</div>}
      </Panel>

      <div>
        <h2 style={{ marginBottom: 12 }}>findings <span className="muted small" style={{ fontWeight: 400 }}>· across every agent of this repository</span></h2>
        <FindingsPanel source={findingsSource} events={events} empty="no findings on this repository yet — they appear after the first run." fileName={`findings-${repo.owner}-${repo.name}`} />
      </div>
    </div>
  );
}
