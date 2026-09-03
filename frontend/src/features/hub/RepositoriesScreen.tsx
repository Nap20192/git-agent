/** Repositories — the hub's home. Table of connected repos (provider, name,
 *  branch, watchers, build, last Событие) + runners / instances / default
 *  build cards. Connect drawer: identity → provider repo → POST /api/repositories
 *  (hub installs the webhook). */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useHubApi, type AgentBuild, type RepoEvent } from "@/api/hub";
import {
  useAsync,
  useBuilds,
  useHubRepositories,
  useIdentityRepos,
  useInstances,
  useMe,
  useRunners,
  useSandboxInstancesHub,
} from "@/hooks";
import { Drawer, Panel, ago, errMsg, sha, shortRef, useScreenCtx, useShell } from "./ui.tsx";

const COLS = "90px 1.4fr 120px 1fr 1fr 1.2fr";

export function RepositoriesScreen() {
  const navigate = useNavigate();
  const api = useHubApi();
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const instancesQ = useInstances();
  const runnersQ = useRunners();
  const sbxQ = useSandboxInstancesHub();
  const [connecting, setConnecting] = useState(false);
  useScreenCtx(null);

  const repos = reposQ.data ?? [];
  const builds = buildsQ.data ?? [];
  const instances = instancesQ.data ?? [];
  const sbx = sbxQ.data ?? [];
  // last Событие per repo — fan-out over the existing per-repo endpoint
  const lastQ = useAsync<Map<number, RepoEvent | undefined>>(
    async () => new Map(await Promise.all(repos.map(async (r) => [r.id, (await api.listRepositoryEvents(r.id))[0]] as const))),
    [repos.map((r) => r.id).join(",")],
  );
  const defaultBuild = builds.find((b) => b.isDefault);
  const buildName = (id?: number | null) => (id != null ? builds.find((b) => b.id === id)?.name : undefined);
  const running = instances.filter((i) => i.status === "running").length;
  const alive = sbx.filter((s) => s.status === "alive").length;

  return (
    <div className="screen">
      <div className="head">
        <div>
          <h1>repositories</h1>
          <div className="sub">{repos.length} connected · every connected repo has a webhook and at least one watcher</div>
        </div>
        <button className="btn primary" onClick={() => setConnecting(true)}>
          + connect repository
        </button>
      </div>

      <div className="box">
        <div className="thead" style={{ "--cols": COLS } as React.CSSProperties}>
          <span>provider</span><span>repository</span><span>branch</span><span>watchers</span><span>build</span><span>last event</span>
        </div>
        {repos.map((r) => {
          const mine = instances.filter((i) => i.repositoryId === r.id);
          const run = mine.filter((i) => i.status === "running").length;
          const last = lastQ.data?.get(r.id);
          return (
            <div key={r.id} className="trow click" style={{ "--cols": COLS } as React.CSSProperties} onClick={() => navigate(`/repos/${r.id}`)}>
              <span className="muted">{r.provider}</span>
              <span className="ellip">
                <span className="muted">{r.owner}/</span>
                <b>{r.name}</b>
              </span>
              <span className="comment ellip">{r.defaultBranch ?? "main"}</span>
              <span>
                {run > 0 && <span className="accent">● </span>}
                {mine.length ? `${run} running · ${mine.length - run} down` : "none"}
              </span>
              <span className="comment ellip">{buildName(r.buildId) ?? (defaultBuild ? `${defaultBuild.name} (default)` : "—")}</span>
              <span className="comment ellip">{last ? `${last.action} · ${shortRef(last.ref)} @ ${sha(last.commitSha)} · ${ago(last.receivedAt)}` : lastQ.loading ? "…" : "no events"}</span>
            </div>
          );
        })}
        {repos.length === 0 && (
          <div className="empty">{reposQ.loading ? "loading…" : "nothing connected yet — connect a repository to install the webhook."}</div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16 }}>
        <Panel label="runners" className="elev pad">
          {(runnersQ.data ?? []).map((x) => (
            <div key={x.id}>
              <div className="kv">
                <span>
                  <b>{x.name}</b> <span className="muted">{x.address}</span>
                </span>
                <span className="comment">
                  {instances.filter((i) => i.runnerId === x.id && i.status === "running").length}/{x.slots} slots
                </span>
              </div>
              <div className="small muted">heartbeat {ago(x.lastHeartbeatAt)}</div>
            </div>
          ))}
          {(runnersQ.data ?? []).length === 0 && <div className="small muted">no runners registered</div>}
        </Panel>
        <Panel label="instances" className="elev pad">
          <div className="kv"><span>agent</span><span className="comment">{running} running · {instances.length - running} down</span></div>
          <div className="kv"><span>sandbox</span><span className="comment">{alive} alive · {sbx.length - alive} dead</span></div>
        </Panel>
        <Panel label="default build" className="elev pad">
          <div>
            <b>{defaultBuild?.name ?? "— none"}</b>
            {defaultBuild?.memoryPreset && <span className="muted"> · {defaultBuild.memoryPreset}</span>}
          </div>
          <div className="small muted pretty">
            serves any repo without its own subscription.{" "}
            <a href="/builds" onClick={(e) => { e.preventDefault(); navigate("/builds"); }}>edit builds →</a>
          </div>
        </Panel>
      </div>

      <ConnectDrawer open={connecting} builds={builds} onClose={() => setConnecting(false)} reload={() => { reposQ.reload(); instancesQ.reload(); }} />
    </div>
  );
}

export function ConnectDrawer({ open, builds, onClose, reload }: { open: boolean; builds: AgentBuild[]; onClose: () => void; reload: () => void }) {
  const api = useHubApi();
  const { say } = useShell();
  const meQ = useMe();
  const reposQ = useHubRepositories();
  const [identityId, setIdentityId] = useState<number | null>(null);
  const [buildId, setBuildId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const identities = meQ.data?.identities ?? [];
  const current = identityId ?? identities[0]?.id ?? null;
  const providerQ = useIdentityRepos(open ? current : null);
  const connected = new Set((reposQ.data ?? []).map((r) => r.externalId));

  const connect = async (externalId: string) => {
    if (current == null) return;
    setBusy(externalId);
    try {
      const r = await api.connectRepository({ identityId: current, externalId, buildId: buildId ? Number(buildId) : undefined });
      say(`connected ${r.owner}/${r.name} · webhook installed`);
      reload();
      reposQ.reload();
      onClose();
    } catch (e) {
      say(errMsg(e, "connect failed"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Drawer open={open} title="connect repository" onClose={onClose}>
      <div className="small comment pretty">pick an identity; the hub lists what that account can see, installs a webhook on connect and assigns the default build.</div>
      <div className="segs">
        {identities.map((i) => (
          <button key={i.id} className={`seg${i.id === current ? " active" : ""}`} onClick={() => setIdentityId(i.id)}>
            {i.provider} · {i.username}
          </button>
        ))}
        {identities.length === 0 && <span className="seg muted">no identities — link one on the account page</span>}
      </div>
      <div className="row">
        <span className="small muted">assign build</span>
        <select className="select" value={buildId} onChange={(e) => setBuildId(e.target.value)}>
          <option value="">default</option>
          {builds.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>
      </div>
      <div className="box">
        {(providerQ.data ?? []).map((p) => (
          <div key={p.externalId} className="lrow" style={{ alignItems: "center" }}>
            <div>
              <span className="muted">{p.owner}/</span><b>{p.name}</b>
              <div className="small muted">{p.defaultBranch ?? "main"} · {p.private ? "private" : "public"}</div>
            </div>
            {connected.has(p.externalId) ? (
              <span className="small muted">connected</span>
            ) : (
              <button className="btn sm" disabled={busy != null} onClick={() => connect(p.externalId)}>
                {busy === p.externalId ? "…" : "connect →"}
              </button>
            )}
          </div>
        ))}
        {providerQ.loading && <div className="empty">loading…</div>}
        {providerQ.error && <div className="empty err">{providerQ.error.message}</div>}
        {!providerQ.loading && (providerQ.data ?? []).length === 0 && current != null && <div className="empty">nothing visible for this identity.</div>}
      </div>
    </Drawer>
  );
}
