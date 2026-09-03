/** /dash — overview of all Экземпляры on existing endpoints (ticket 012):
 *  running/down, События over 24h per repo, latest Находки by severity.
 *  15s polling — an overview, not a live view. */
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useHubApi, type Finding, type RepoEvent } from "@/api/hub";
import { useAsync, useBuilds, useHubRepositories, useInstances, useLlmConnections, useRunners } from "@/hooks";
import { FindingsTable } from "./PlaygroundScreen.tsx";
import { Dot, Onboarding, Panel, ago, useScreenCtx } from "./ui.tsx";

const POLL_MS = 15000;
const DAY_MS = 24 * 60 * 60 * 1000;
const SEVERITIES = ["critical", "high", "medium", "low", "info"];
const ICOLS = "3ch 1.2fr 1.4fr 90px 1.4fr";

export function DashScreen() {
  const api = useHubApi();
  const navigate = useNavigate();
  useScreenCtx(null);
  const instancesQ = useInstances();
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const runnersQ = useRunners();
  const llmQ = useLlmConnections();
  const repos = reposQ.data ?? [];
  const instances = instancesQ.data ?? [];

  // fan-out over existing endpoints: events per repo, findings per instance
  const eventsQ = useAsync<Map<number, RepoEvent[]>>(
    async () => new Map(await Promise.all(repos.map(async (r) => [r.id, await api.listRepositoryEvents(r.id)] as const))),
    [repos.map((r) => r.id).join(",")],
  );
  const findingsQ = useAsync<Finding[]>(
    async () => (await Promise.all(instances.map((i) => api.listInstanceFindings(i.id)))).flat().sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? "")),
    [instances.map((i) => i.id).join(",")],
  );
  const reloadRef = useRef(() => {});
  reloadRef.current = () => { instancesQ.reload(); reposQ.reload(); runnersQ.reload(); eventsQ.reload(); findingsQ.reload(); };
  useEffect(() => {
    const t = setInterval(() => reloadRef.current(), POLL_MS);
    return () => clearInterval(t);
  }, []);

  const now = Date.now();
  const running = instances.filter((i) => i.status === "running").length;
  const fresh = (rid: number) => (eventsQ.data?.get(rid) ?? []).filter((e) => now - new Date(e.receivedAt).getTime() < DAY_MS).length;
  const events24 = repos.reduce((n, r) => n + fresh(r.id), 0);
  const findings = findingsQ.data ?? [];
  const sev = SEVERITIES.map((s) => [s, findings.filter((f) => f.severity === s).length] as const).filter(([, n]) => n > 0);
  const buildName = (id: number) => (buildsQ.data ?? []).find((b) => b.id === id)?.name ?? `instance`;
  const repoName = (id: number) => { const r = repos.find((x) => x.id === id); return r ? `${r.owner}/${r.name}` : `repo #${id}`; };
  const onboarding = { llm: (llmQ.data ?? []).length > 0, build: (buildsQ.data ?? []).some((b) => b.isDefault), repo: repos.length > 0 };
  const showOnboarding = !reposQ.loading && !buildsQ.loading && !llmQ.loading && !(onboarding.llm && onboarding.build && onboarding.repo);

  return (
    <div className="screen">
      <div>
        <h1>dash</h1>
        <div className="sub">every instance at a glance: who is up, what arrived in 24h, what was found.</div>
      </div>
      {showOnboarding && <Onboarding state={onboarding} />}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16 }}>
        <Panel label="instances" className="elev pad"><div className="kv"><span>running / down</span><span className="comment">{running} / {instances.length - running}</span></div></Panel>
        <Panel label="events 24h" className="elev pad"><div className="kv"><span>received</span><span className="comment">{eventsQ.data ? events24 : "…"}</span></div></Panel>
        <Panel label="findings" className="elev pad">
          {sev.map(([s, n]) => (<div key={s} className="kv"><span>{s}</span><span className="comment">{n}</span></div>))}
          {sev.length === 0 && <div className="kv"><span>total</span><span className="comment">{findingsQ.loading ? "…" : 0}</span></div>}
        </Panel>
        <Panel label="runners" className="elev pad"><div className="kv"><span>registered</span><span className={(runnersQ.data ?? []).length ? "comment" : "err"}>{(runnersQ.data ?? []).length}{!runnersQ.loading && (runnersQ.data ?? []).length === 0 ? " — nothing can run" : ""}</span></div></Panel>
      </div>
      <div className="box">
        <div className="thead" style={{ "--cols": ICOLS } as React.CSSProperties}><span></span><span>build</span><span>repository</span><span>events 24h</span><span>sandbox instance · updated</span></div>
        {instances.map((i) => (
          <div key={i.id} className="trow click" style={{ "--cols": ICOLS } as React.CSSProperties} onClick={() => navigate(`/instances/${i.id}`)}>
            <Dot on={i.status === "running"} pulse={i.status === "running"} />
            <span><b>{buildName(i.buildId)}</b> <span className="muted">#{i.id} · {i.status}</span></span>
            <span className="comment ellip">{repoName(i.repositoryId)}</span>
            <span className="comment">{eventsQ.data ? fresh(i.repositoryId) : "…"}</span>
            <span className="muted small ellip">{i.sandboxExternalId ?? "no sandbox instance yet"}{i.sandboxStatus ? ` (${i.sandboxStatus})` : ""} · {ago(i.updatedAt)}</span>
          </div>
        ))}
        {instances.length === 0 && <div className="empty">{instancesQ.loading && instancesQ.data === undefined ? "loading…" : <>no agents yet — an agent appears when a connected repository gets its first event or you press run agent on its page. <a href="/repos" onClick={(e) => { e.preventDefault(); navigate("/repos"); }}>repositories →</a></>}</div>}
      </div>
      <div>
        <h2 style={{ marginBottom: 12 }}>latest findings <span className="muted small" style={{ fontWeight: 400 }}>· {findings.length}</span></h2>
        <FindingsTable rows={findings.slice(0, 12)} loading={findingsQ.loading && findingsQ.data === undefined} empty="no findings yet." />
      </div>
    </div>
  );
}
