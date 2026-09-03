/** Repository page. Watchers = the repo's Экземпляры (one per subscribed
 *  Сборка; no subscriptions → the default Сборка covers everything) with
 *  playground/stop/unsubscribe, a subscribe form (build + actions + ref mask),
 *  the Событие journal and a chat with the active watcher. */
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useHubApi, type Subscription } from "@/api/hub";
import { useBuilds, useHubRepositories, useInstances, useRepoEvents, useSubscriptions } from "@/hooks";
import { InstanceChatPanel } from "./InstanceChatPanel.tsx";
import { Dot, Panel, ago, errMsg, sha, shortRef, useScreenCtx, useShell } from "./ui.tsx";

const JCOLS = "150px 1fr 110px 1fr";

const subText = (sub?: Subscription) =>
  sub ? `subscribed: ${sub.actions.length ? sub.actions.join(", ") : "all actions"} · ${sub.refMask ?? "any ref"}` : "served by default build · no subscription";

export function RepoScreen() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const api = useHubApi();
  const { say } = useShell();
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const instancesQ = useInstances();
  const eventsQ = useRepoEvents(id);
  const subsQ = useSubscriptions(id);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ build: "", actions: "", ref: "" });

  const repo = (reposQ.data ?? []).find((r) => r.id === id);
  useScreenCtx(repo ? `${repo.owner}/${repo.name}` : null);
  const builds = buildsQ.data ?? [];
  const events = eventsQ.data ?? [];
  const subs = subsQ.data ?? [];
  const mine = (instancesQ.data ?? []).filter((i) => i.repositoryId === id);
  const buildName = (bid: number) => builds.find((b) => b.id === bid)?.name ?? `build #${bid}`;
  const subFor = (bid: number) => subs.find((s) => s.buildId === bid);
  // chat target: the running watcher, else any
  const chatInst = mine.find((i) => i.status === "running") ?? mine[0];
  // subscriptions whose Сборка has no Экземпляр yet (raised on the first Событие)
  const pending = subs.filter((s) => !mine.some((i) => i.buildId === s.buildId));

  if (!repo) return <div className="gate">{reposQ.loading ? "loading…" : "this repository isn't connected."}</div>;

  const run = async (mode?: "full") => {
    if (mode === "full" && !window.confirm("Full scan is a long and expensive run — start it?")) return;
    setBusy(true);
    try {
      const res = await api.triggerRepository(repo.id, mode ? { mode } : undefined);
      say(`${mode === "full" ? "full scan" : "manual run"} @ ${sha(res.event.commitSha)} → ${res.instances.length} instance(s) raised`);
      const target = res.instances.find((i) => i.id === chatInst?.id) ?? res.instances[0];
      if (target) navigate(`/instances/${target.id}`);
      else {
        eventsQ.reload();
        instancesQ.reload();
      }
    } catch (e) {
      say(errMsg(e, "trigger failed"));
    } finally {
      setBusy(false);
    }
  };
  const act = async (fn: () => Promise<void>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      say(ok);
    } catch (e) {
      say(errMsg(e, "failed"));
    } finally {
      setBusy(false);
    }
  };
  const stop = (instId: number) => act(async () => { await api.stopInstance(instId); instancesQ.reload(); }, `instance #${instId} stopped`);
  const unsub = (s: Subscription) => act(async () => { await api.deleteSubscription(s.id); subsQ.reload(); }, `unsubscribed ${buildName(s.buildId)}`);
  const disconnect = () => {
    if (!window.confirm(`Disconnect ${repo.owner}/${repo.name}? The webhook is removed; agents' knowledge stays in their checkpoints.`)) return;
    act(async () => { await api.disconnectRepository(repo.id); navigate("/repos"); }, `disconnected ${repo.name} · webhook removed`);
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
          <div className="sub comment">{repo.defaultBranch ?? "main"} · connected {ago(repo.connectedAt)} · webhook installed</div>
        </div>
        <div className="row">
          <button className="btn primary" disabled={busy} onClick={() => run()}>❯ trigger run @ {repo.defaultBranch ?? "main"}</button>
          <button className="btn md" disabled={busy} onClick={() => run("full")}>full scan</button>
          <button className="btn md danger" disabled={busy} onClick={disconnect}>disconnect</button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 16, flex: 1, minHeight: 0 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20, minWidth: 0 }}>
          <Panel label="watchers" dim={mine.length + pending.length}>
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
                      sandbox {w.sandboxExternalId ?? "none"}{w.sandboxStatus ? ` (${w.sandboxStatus})` : ""} · runner {w.runnerId ?? "—"} · updated {ago(w.updatedAt)}
                    </div>
                    <div className="small muted" style={{ marginTop: 2 }}>{subText(sub)}</div>
                  </div>
                  <div className="row" style={{ flexWrap: "nowrap" }}>
                    <button className="btn" onClick={() => navigate(`/instances/${w.id}`)}>playground →</button>
                    {running && <button className="btn" disabled={busy} onClick={() => stop(w.id)}>stop</button>}
                    {sub && <button className="btn danger" disabled={busy} onClick={() => unsub(sub)}>unsubscribe</button>}
                  </div>
                </div>
              );
            })}
            {pending.map((s) => (
              <div key={`s${s.id}`} className="lrow" style={{ padding: 12 }}>
                <div>
                  <div><Dot on={false} /><b>{buildName(s.buildId)}</b> <span className="muted">· not raised yet</span></div>
                  <div className="small muted" style={{ marginTop: 2 }}>{subText(s)} · instance appears on the first matching event</div>
                </div>
                <button className="btn danger" disabled={busy} onClick={() => unsub(s)}>unsubscribe</button>
              </div>
            ))}
            {mine.length + pending.length === 0 && (
              <div className="empty small">{instancesQ.loading ? "loading…" : "no watchers — the default build handles every event. subscribe one to narrow or split the coverage."}</div>
            )}
            <div className="row" style={{ padding: 12, background: "var(--bg-elevated)" }}>
              <span className="small muted">subscribe build</span>
              <select className="select" value={f.build} onChange={(e) => setF({ ...f, build: e.target.value })}>
                {builds.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}{b.isDefault ? " (default)" : ""}</option>
                ))}
              </select>
              <input className="input" style={{ flex: 1, minWidth: 180 }} value={f.actions} onChange={(e) => setF({ ...f, actions: e.target.value })} placeholder="actions · push, pull_request.opened · empty = all" />
              <input className="input" style={{ width: 160 }} value={f.ref} onChange={(e) => setF({ ...f, ref: e.target.value })} placeholder="ref mask · release/*" />
              <button className="btn" disabled={busy || builds.length === 0} onClick={addSub}>+ add</button>
            </div>
          </Panel>

          <Panel label="journal" dim={`${events.length} events`} className="col" >
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
              {events.length === 0 && <div className="empty small">{eventsQ.loading ? "loading…" : "nothing yet — push to the repository and the webhook delivers the first event here."}</div>}
            </div>
          </Panel>
        </div>

        <Panel label="chat" dim={chatInst ? `${buildName(chatInst.buildId)} #${chatInst.id}` : "no watcher"} className="col elev" >
          <div style={{ display: "flex", flexDirection: "column", minHeight: 420, flex: 1 }}>
            <InstanceChatPanel
              instanceId={chatInst?.id ?? null}
              empty="ask the watcher what it has accumulated on this repo. a down instance wakes on the first message."
              onStatusChange={instancesQ.reload}
            />
          </div>
        </Panel>
      </div>
    </div>
  );
}
