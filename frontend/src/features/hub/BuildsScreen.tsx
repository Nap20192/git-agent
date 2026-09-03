/** Сборки Агентов (stored definitions: prompt, connections, memory preset,
 *  limits) + llm / sandbox connections (keys masked) + sandbox instances
 *  (no ttl, killed only on command) + runners. Row click → edit drawer. */
import { useState } from "react";
import { useHubApi, type AgentBuild, type LlmConnection, type SandboxConnection } from "@/api/hub";
import { useBuilds, useInstances, useLlmConnections, useRunners, useSandboxConnections, useSandboxInstancesHub } from "@/hooks";
import { limitsText } from "./PlaygroundScreen.tsx";
import { Dot, Drawer, ago, errMsg, useScreenCtx, useShell } from "./ui.tsx";

const BCOLS = "1.2fr 1fr 1fr 110px 1.2fr 1fr 200px";

/** Known limits keys (agent/core/lead/graph.py::_lead_features). */
const LIMIT_FIELDS = [
  { key: "maxSubagents", label: "max subagents", ph: "3" },
  { key: "maxTotalSubagents", label: "total delegations", ph: "6" },
  { key: "tokenBudget", label: "token budget", ph: "500000" },
  { key: "subagentTimeout", label: "subagent timeout, s", ph: "600" },
  { key: "queueTimeout", label: "queue timeout, s", ph: "300" },
] as const;

export function BuildsScreen() {
  const api = useHubApi();
  const { say } = useShell();
  useScreenCtx(null);
  const buildsQ = useBuilds();
  const llmQ = useLlmConnections();
  const sbxQ = useSandboxConnections();
  const instQ = useSandboxInstancesHub();
  const runnersQ = useRunners();
  const agentsQ = useInstances();
  const [drawer, setDrawer] = useState<"build" | "llm" | "sbx" | null>(null);
  const [editing, setEditing] = useState<AgentBuild | null>(null);
  const [busy, setBusy] = useState(false);

  const builds = buildsQ.data ?? [];
  const llms = llmQ.data ?? [];
  const sbxs = sbxQ.data ?? [];
  const sbxInst = instQ.data ?? [];
  const agents = agentsQ.data ?? [];
  const llmName = (id?: number) => llms.find((c) => c.id === id)?.name ?? "—";
  const sbxName = (id?: number) => sbxs.find((c) => c.id === id)?.name ?? "—";

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
  const makeDefault = (b: AgentBuild) => act(async () => { await api.updateBuild(b.id, { ...b, isDefault: true }); buildsQ.reload(); }, `${b.name} is now the default build`);
  const removeBuild = (b: AgentBuild) => window.confirm(`delete build ${b.name}?`) && act(async () => { await api.deleteBuild(b.id); buildsQ.reload(); }, `deleted build ${b.name}`);
  const removeLlm = (c: LlmConnection) => window.confirm(`delete llm connection ${c.name}?`) && act(async () => { await api.deleteLlmConnection(c.id); llmQ.reload(); }, `deleted llm connection ${c.name}`);
  const removeSbx = (c: SandboxConnection) => window.confirm(`delete sandbox connection ${c.name}?`) && act(async () => { await api.deleteSandboxConnection(c.id); sbxQ.reload(); }, `deleted sandbox connection ${c.name}`);
  const spawn = (c: SandboxConnection) => act(async () => { const s = await api.createSandboxInstance({ sandboxConnectionId: c.id }); instQ.reload(); say(`sandbox ${s.externalId} created on ${c.name}`); }, "");
  const kill = (id: number, ext: string) => window.confirm(`kill sandbox ${ext}?`) && act(async () => { await api.killSandboxInstance(id); instQ.reload(); }, `killed ${ext}`);

  return (
    <div className="screen" style={{ gap: 28 }}>
      <div>
        <div className="head" style={{ marginBottom: 12 }}>
          <div>
            <h1>builds</h1>
            <div className="sub">an agent build is a stored definition — prompt, connections, memory preset, limits. not a live process.</div>
          </div>
          <button className="btn primary" onClick={() => { setEditing(null); setDrawer("build"); }}>+ new build</button>
        </div>
        <div className="box">
          <div className="thead" style={{ "--cols": BCOLS } as React.CSSProperties}>
            <span>name</span><span>llm</span><span>sandbox</span><span>memory</span><span>limits</span><span>created</span><span></span>
          </div>
          {builds.map((b) => (
            <div key={b.id} className="trow click" style={{ "--cols": BCOLS, padding: "8px 12px" } as React.CSSProperties} onClick={() => { setEditing(b); setDrawer("build"); }}>
              <span>
                <b>{b.name}</b>{b.isDefault && <span className="accent"> ● default</span>}
                <div className="small muted pretty">{b.prompt || "no prompt"}</div>
              </span>
              <span className="comment ellip">{llmName(b.llmConnectionId)}</span>
              <span className="comment ellip">{sbxName(b.sandboxConnectionId)}</span>
              <span className="comment">{b.memoryPreset ?? "—"}</span>
              <span className="comment small">{limitsText(b.limits)}</span>
              <span className="muted small">{ago(b.createdAt)}</span>
              <span className="row" style={{ flexWrap: "nowrap" }} onClick={(e) => e.stopPropagation()}>
                {!b.isDefault && <button className="btn sm" disabled={busy} onClick={() => makeDefault(b)}>make default</button>}
                <button className="btn sm danger" disabled={busy} onClick={() => removeBuild(b)}>delete</button>
              </span>
            </div>
          ))}
          {builds.length === 0 && <div className="empty">{buildsQ.loading ? "loading…" : "no builds — create one; the default build serves every repo without a subscription."}</div>}
        </div>
      </div>

      <div className="grid2" style={{ gap: 16 }}>
        <div>
          <div className="head" style={{ marginBottom: 12 }}>
            <div><h2>llm connections</h2><div className="sub">only the key mask ever crosses the wire.</div></div>
            <button className="btn" onClick={() => setDrawer("llm")}>+ add</button>
          </div>
          <div className="box">
            {llms.map((c) => (
              <div key={c.id} className="lrow">
                <div>
                  <b>{c.name}</b> <span className="muted">· {c.model}</span>
                  <div className="small comment">{c.apiBase} · key {c.apiKeyMasked}</div>
                </div>
                <button className="btn sm danger" disabled={busy} onClick={() => removeLlm(c)}>delete</button>
              </div>
            ))}
            {llms.length === 0 && <div className="empty small">{llmQ.loading ? "loading…" : "none."}</div>}
          </div>
        </div>
        <div>
          <div className="head" style={{ marginBottom: 12 }}>
            <div><h2>sandbox connections</h2><div className="sub">opensandbox endpoints the hub provisions from.</div></div>
            <button className="btn" onClick={() => setDrawer("sbx")}>+ add</button>
          </div>
          <div className="box">
            {sbxs.map((c) => (
              <div key={c.id} className="lrow">
                <div>
                  <b>{c.name}</b> <span className="muted">· {c.image || "default image"}</span>
                  <div className="small comment">{c.domain} · key {c.apiKeyMasked ?? "—"}</div>
                </div>
                <div className="row" style={{ flexWrap: "nowrap" }}>
                  <button className="btn sm" disabled={busy} onClick={() => spawn(c)}>+ instance</button>
                  <button className="btn sm danger" disabled={busy} onClick={() => removeSbx(c)}>delete</button>
                </div>
              </div>
            ))}
            {sbxs.length === 0 && <div className="empty small">{sbxQ.loading ? "loading…" : "none."}</div>}
          </div>
        </div>
      </div>

      <div className="grid2" style={{ gap: 16 }}>
        <div>
          <h2 style={{ marginBottom: 12 }}>sandbox instances <span className="muted small" style={{ fontWeight: 400 }}>· no ttl — killed only on command</span></h2>
          <div className="box">
            {sbxInst.map((s) => {
              const alive = s.status === "alive";
              const usedBy = agents.filter((a) => a.sandboxInstanceId === s.id).map((a) => `#${a.id}`);
              return (
                <div key={s.id} className="lrow" style={{ alignItems: "center" }}>
                  <div>
                    <Dot on={alive} /><b>{s.externalId}</b> <span className="muted">· {sbxName(s.sandboxConnectionId)} · {s.status}</span>
                    <div className="small comment">created {ago(s.createdAt)}{s.killedAt ? ` · killed ${ago(s.killedAt)}` : ""} · used by {usedBy.length ? `instance ${usedBy.join(", ")}` : "nobody"}</div>
                  </div>
                  {alive && <button className="btn sm danger" disabled={busy} onClick={() => kill(s.id, s.externalId)}>kill</button>}
                </div>
              );
            })}
            {sbxInst.length === 0 && <div className="empty small" style={{ padding: 12 }}>{instQ.loading ? "loading…" : "none provisioned."}</div>}
          </div>
        </div>
        <div>
          <h2 style={{ marginBottom: 12 }}>runners</h2>
          <div className="box">
            {(runnersQ.data ?? []).map((x) => (
              <div key={x.id} className="lrow">
                <div>
                  <b>{x.name}</b> <span className="muted">· {x.address}</span>
                  <div className="small comment">heartbeat {ago(x.lastHeartbeatAt)}</div>
                </div>
                <span className="comment">{agents.filter((a) => a.runnerId === x.id && a.status === "running").length}/{x.slots} slots</span>
              </div>
            ))}
            {(runnersQ.data ?? []).length === 0 && <div className="empty small" style={{ padding: 12 }}>{runnersQ.loading ? "loading…" : "no runners registered."}</div>}
          </div>
        </div>
      </div>

      <BuildDrawer open={drawer === "build"} build={editing} llms={llms} sandboxes={sbxs} onClose={() => setDrawer(null)} reload={buildsQ.reload} />
      <LlmDrawer open={drawer === "llm"} onClose={() => setDrawer(null)} reload={llmQ.reload} />
      <SbxDrawer open={drawer === "sbx"} onClose={() => setDrawer(null)} reload={sbxQ.reload} />
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="flabel">{label}</span>
      {children}
    </label>
  );
}

function BuildDrawer({ open, build, llms, sandboxes, onClose, reload }: { open: boolean; build: AgentBuild | null; llms: LlmConnection[]; sandboxes: SandboxConnection[]; onClose: () => void; reload: () => void }) {
  const api = useHubApi();
  const { say } = useShell();
  const [f, setF] = useState({ name: "", llm: "", sbx: "", prompt: "", memory: "", isDefault: false });
  const [lim, setLim] = useState<Record<string, string>>({});
  // unknown keys of an existing limits object are kept as-is, never dropped
  const [extra, setExtra] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [seeded, setSeeded] = useState<number | null | undefined>(undefined);

  // seed form state when the drawer opens for a different build (or create)
  const seedKey = build?.id ?? null;
  if (open && seeded !== seedKey) {
    setSeeded(seedKey);
    setF({ name: build?.name ?? "", llm: build?.llmConnectionId != null ? String(build.llmConnectionId) : "", sbx: build?.sandboxConnectionId != null ? String(build.sandboxConnectionId) : "", prompt: build?.prompt ?? "", memory: build?.memoryPreset ?? "", isDefault: build?.isDefault ?? false });
    const vals: Record<string, string> = {};
    const ex: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(build?.limits ?? {})) {
      if (LIMIT_FIELDS.some((x) => x.key === k)) vals[k] = String(v);
      else ex[k] = v;
    }
    setLim(vals);
    setExtra(ex);
  }
  if (!open && seeded !== undefined) setSeeded(undefined);

  const submit = async () => {
    if (!f.name.trim()) return say("build needs a name");
    setBusy(true);
    try {
      const limits: Record<string, unknown> = { ...extra };
      for (const x of LIMIT_FIELDS) {
        const v = (lim[x.key] ?? "").trim();
        if (v !== "" && Number.isFinite(Number(v))) limits[x.key] = Number(v);
      }
      const input = { name: f.name.trim(), llmConnectionId: f.llm ? Number(f.llm) : undefined, sandboxConnectionId: f.sbx ? Number(f.sbx) : undefined, prompt: f.prompt.trim() || null, memoryPreset: f.memory.trim() || null, limits, isDefault: f.isDefault };
      if (build) await api.updateBuild(build.id, input);
      else await api.createBuild(input);
      say(`${build ? "saved" : "created"} build ${input.name}`);
      reload();
      onClose();
    } catch (e) {
      say(errMsg(e, "save failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open={open} title={build ? `edit build · ${build.name}` : "new build"} onClose={onClose}>
      <Field label="name"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="release-reviewer" /></Field>
      <Field label="prompt"><textarea className="textarea" rows={4} value={f.prompt} onChange={(e) => setF({ ...f, prompt: e.target.value })} placeholder="Review every push for security issues." /></Field>
      <div className="grid2">
        <Field label="llm connection">
          <select className="select" value={f.llm} onChange={(e) => setF({ ...f, llm: e.target.value })}>
            <option value="">—</option>
            {llms.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
          </select>
        </Field>
        <Field label="sandbox connection">
          <select className="select" value={f.sbx} onChange={(e) => setF({ ...f, sbx: e.target.value })}>
            <option value="">—</option>
            {sandboxes.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
          </select>
        </Field>
      </div>
      <Field label="memory preset"><input className="input" value={f.memory} onChange={(e) => setF({ ...f, memory: e.target.value })} placeholder="prod_v2" /></Field>
      <div className="flabel">limits · empty = runner default</div>
      <div className="grid3">
        {LIMIT_FIELDS.map((x) => (
          <Field key={x.key} label={x.label}><input className="input" type="number" value={lim[x.key] ?? ""} onChange={(e) => setLim({ ...lim, [x.key]: e.target.value })} placeholder={x.ph} /></Field>
        ))}
      </div>
      <label className="check"><input type="checkbox" checked={f.isDefault} onChange={(e) => setF({ ...f, isDefault: e.target.checked })} /><span>make this the default build</span></label>
      <button className="btn lg primary" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={submit}>❯ {build ? "save build" : "create build"}</button>
    </Drawer>
  );
}

function LlmDrawer({ open, onClose, reload }: { open: boolean; onClose: () => void; reload: () => void }) {
  const api = useHubApi();
  const { say } = useShell();
  const [f, setF] = useState({ name: "", base: "", model: "", key: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!f.name.trim() || !f.key || !f.base.trim() || !f.model.trim()) return say("name, api base, model and api key are required");
    setBusy(true);
    try {
      await api.createLlmConnection({ name: f.name.trim(), apiBase: f.base.trim(), apiKey: f.key, model: f.model.trim() });
      say(`added llm connection ${f.name.trim()}`);
      setF({ name: "", base: "", model: "", key: "" });
      reload();
      onClose();
    } catch (e) {
      say(errMsg(e, "create failed"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Drawer open={open} title="new llm connection" onClose={onClose}>
      <Field label="name"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="openrouter" /></Field>
      <Field label="api base"><input className="input" value={f.base} onChange={(e) => setF({ ...f, base: e.target.value })} placeholder="https://openrouter.ai/api/v1" /></Field>
      <Field label="model"><input className="input" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} placeholder="anthropic/claude-sonnet-4" /></Field>
      <Field label="api key · stored masked, never returned"><input className="input" type="password" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} placeholder="sk-…" /></Field>
      <button className="btn lg primary" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={submit}>❯ add connection</button>
    </Drawer>
  );
}

function SbxDrawer({ open, onClose, reload }: { open: boolean; onClose: () => void; reload: () => void }) {
  const api = useHubApi();
  const { say } = useShell();
  const [f, setF] = useState({ name: "", domain: "", image: "", key: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!f.name.trim() || !f.domain.trim()) return say("name and domain are required");
    setBusy(true);
    try {
      await api.createSandboxConnection({ name: f.name.trim(), domain: f.domain.trim(), apiKey: f.key.trim() || undefined, image: f.image.trim() || undefined });
      say(`added sandbox connection ${f.name.trim()}`);
      setF({ name: "", domain: "", image: "", key: "" });
      reload();
      onClose();
    } catch (e) {
      say(errMsg(e, "create failed"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Drawer open={open} title="new sandbox connection" onClose={onClose}>
      <Field label="name"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="local-opensandbox" /></Field>
      <Field label="domain"><input className="input" value={f.domain} onChange={(e) => setF({ ...f, domain: e.target.value })} placeholder="http://localhost:8090" /></Field>
      <Field label="image"><input className="input" value={f.image} onChange={(e) => setF({ ...f, image: e.target.value })} placeholder="opensandbox/base" /></Field>
      <Field label="api key · optional"><input className="input" type="password" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} /></Field>
      <button className="btn lg primary" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={submit}>❯ add connection</button>
    </Drawer>
  );
}
