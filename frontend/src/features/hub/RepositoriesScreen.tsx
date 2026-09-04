/** Repositories — the hub's home. Table of connected repos (provider, name,
 *  branch, watchers, build, last Событие) + runners / instances / default
 *  build cards. Connect drawer: identity → provider repo → POST /api/repositories
 *  (hub installs the webhook), or a public repo by URL (watch mode: no webhook,
 *  manual runs only). */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useHubApi, type AgentBuild, type RepoEvent } from "@/api/hub";
import {
  useAsync,
  useBuilds,
  useHubRepositories,
  useIdentityRepos,
  useLlmConnections,
  useInstances,
  useMe,
  useRunners,
  useSandboxInstancesHub,
} from "@/hooks";
import { Drawer, Onboarding, Panel, ago, sha, shortRef, useScreenCtx, useShell } from "./ui.tsx";

const COLS = "90px 1.4fr 120px 1fr 1fr 1.2fr";

export function RepositoriesScreen() {
  const navigate = useNavigate();
  const api = useHubApi();
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const llmQ = useLlmConnections();
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
  const buildName = (id?: number | null) => (id != null ? builds.find((b) => b.id === id)?.name : undefined);
  const running = instances.filter((i) => i.status === "running").length;
  const alive = sbx.filter((s) => s.status === "alive").length;
  const loaded = !reposQ.loading && !buildsQ.loading && !llmQ.loading;
  const onboarding = { llm: (llmQ.data ?? []).length > 0, build: builds.length > 0, repo: repos.length > 0 };
  const showOnboarding = loaded && !(onboarding.llm && onboarding.build && onboarding.repo);

  return (
    <div className="screen">
      <div className="head">
        <div>
          <h1>repositories</h1>
          <div className="sub">{repos.length} connected · hook repos get events by webhook, <span className="tag">watch</span> repos run manually</div>
        </div>
        <button className="btn primary" onClick={() => setConnecting(true)}>
          + connect repository
        </button>
      </div>

      {showOnboarding && <Onboarding state={onboarding} onConnect={() => setConnecting(true)} />}

      <div className="box">
        <div className="thead" style={{ "--cols": COLS } as React.CSSProperties}>
          <span>provider</span><span>repository</span><span>branch</span><span>agents</span><span>build</span><span>last event</span>
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
                {r.mode === "watch" && <span className="tag" title="no webhook — run manually">watch</span>}
              </span>
              <span className="comment ellip">{r.defaultBranch ?? "main"}</span>
              <span>
                {run > 0 && <span className="accent">● </span>}
                {mine.length ? `${run} running · ${mine.length - run} down` : "none"}
              </span>
              <span className="comment ellip">{buildName(r.buildId) ?? <span className="err">no subscription — nothing will run</span>}</span>
              <span className="comment ellip">{last ? `${last.action} · ${shortRef(last.ref)} @ ${sha(last.commitSha)} · ${ago(last.receivedAt)}` : lastQ.loading ? "…" : "no events"}</span>
            </div>
          );
        })}
        {repos.length === 0 && (
          <div className="empty">
            {reposQ.loading ? "loading…" : <>nothing connected yet — <a href="/repos" onClick={(e) => { e.preventDefault(); setConnecting(true); }}>connect your own repository</a> (webhook) or watch a public one by url.</>}
          </div>
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
          <div className="kv"><span>agents</span><span className="comment">{running} running · {instances.length - running} down</span></div>
          <div className="kv"><span>sandbox instances</span><span className="comment">{alive} alive · {sbx.length - alive} dead</span></div>
        </Panel>
        <Panel label="builds" className="elev pad">
          <div><b>{builds.length ? builds.map((b) => b.name).join(", ") : "none"}</b></div>
          <div className="small muted pretty">
            {builds.length ? "a repo runs only the builds subscribed to it — subscribe on the repo page." : <span className="err">no builds yet — nothing can run.</span>}{" "}
            <a href="/builds" onClick={(e) => { e.preventDefault(); navigate("/builds"); }}>{builds.length ? "edit builds →" : "create a build →"}</a>
          </div>
        </Panel>
      </div>

      <ConnectDrawer open={connecting} builds={builds} onClose={() => setConnecting(false)} reload={() => { reposQ.reload(); instancesQ.reload(); }} />
    </div>
  );
}

export function ConnectDrawer({ open, builds, onClose, reload }: { open: boolean; builds: AgentBuild[]; onClose: () => void; reload: () => void }) {
  const api = useHubApi();
  const { say, fail } = useShell();
  const meQ = useMe();
  const reposQ = useHubRepositories();
  const [identityId, setIdentityId] = useState<number | null>(null);
  const [buildId, setBuildId] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const identities = meQ.data?.identities ?? [];
  const current = identityId ?? identities[0]?.id ?? null;
  const providerQ = useIdentityRepos(open ? current : null);
  const connected = new Set((reposQ.data ?? []).map((r) => r.externalId));

  const connect = async (input: { externalId: string } | { url: string }) => {
    const build = buildId ? Number(buildId) : undefined;
    setBusy("url" in input ? "url" : input.externalId);
    try {
      const r =
        "url" in input
          ? await api.connectRepository({ url: input.url, buildId: build })
          : current == null
            ? undefined
            : await api.connectRepository({ identityId: current, externalId: input.externalId, buildId: build });
      if (!r) return;
      say(`connected ${r.owner}/${r.name} · ${r.mode === "watch" ? "watch mode: no webhook — run manually" : "webhook installed"}`);
      setUrl("");
      reload();
      reposQ.reload();
      onClose();
    } catch (e) {
      fail(e, "connect failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Drawer open={open} title="connect repository" onClose={onClose}>
      <div className="small comment pretty">pick an identity; the hub lists what that account can see and installs a webhook on connect. nothing runs until a build is subscribed — pick one below or later on the repo page.</div>
      <div className="segs">
        {identities.map((i) => (
          <button key={i.id} className={`seg${i.id === current ? " active" : ""}`} onClick={() => setIdentityId(i.id)}>
            {i.provider} · {i.username}
          </button>
        ))}
        {identities.length === 0 && <span className="seg muted">no identities — link one on the account page</span>}
      </div>
      <div className="row">
        <span className="small muted">subscribe build</span>
        <select className="select" value={buildId} onChange={(e) => setBuildId(e.target.value)}>
          <option value="">none — subscribe later on the repo page</option>
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
              <button className="btn sm" disabled={busy != null} onClick={() => connect({ externalId: p.externalId })}>
                {busy === p.externalId ? "…" : "connect →"}
              </button>
            )}
          </div>
        ))}
        {providerQ.loading && <div className="empty">loading…</div>}
        {providerQ.error && <div className="empty err pretty">can't list this account's repositories: {providerQ.error.message}</div>}
        {!providerQ.loading && (providerQ.data ?? []).length === 0 && current != null && <div className="empty">nothing visible for this identity.</div>}
      </div>

      <div className="small comment pretty" style={{ marginTop: 16 }}>
        or <span className="tag">watch</span> someone else's public repository by URL: no webhook is installed (no admin rights needed) — you run the agent manually.
      </div>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) void connect({ url: url.trim() });
        }}
      >
        <input
          className="input"
          style={{ flex: 1 }}
          type="url"
          placeholder="https://github.com/owner/repo"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={busy != null}
        />
        <button className="btn sm" type="submit" disabled={busy != null || !url.trim()}>
          {busy === "url" ? "…" : "connect →"}
        </button>
      </form>
    </Drawer>
  );
}
