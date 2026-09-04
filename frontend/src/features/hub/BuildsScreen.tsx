/** Сборки Агентов (stored definitions: prompt, connections, memory preset,
 *  limits) + llm / sandbox connections (keys masked) + sandbox instances
 *  (no ttl, killed only on command) + runners. Row click → edit drawer. */
import { useState } from "react";
import { useHubApi, type AgentBuild, type LlmConnection, type SandboxConnection } from "@/api/hub";
import { useBuilds, useDefaults, useInstances, useLlmConnections, useRunners, useSandboxConnections, useSandboxInstancesHub } from "@/hooks";
import { limitsText } from "./PlaygroundScreen.tsx";
import { Dot, Drawer, ago, useScreenCtx, useShell } from "./ui.tsx";

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
  const { say, fail } = useShell();
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
  const [showDead, setShowDead] = useState(false);

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
      fail(e, "failed");
    } finally {
      setBusy(false);
    }
  };
  const removeBuild = (b: AgentBuild) => window.confirm(`delete build ${b.name}?`) && act(async () => { await api.deleteBuild(b.id); buildsQ.reload(); }, `deleted build ${b.name}`);
  const removeLlm = (c: LlmConnection) => window.confirm(`delete llm connection ${c.name}?`) && act(async () => { await api.deleteLlmConnection(c.id); llmQ.reload(); }, `deleted llm connection ${c.name}`);
  const removeSbx = (c: SandboxConnection) => window.confirm(`delete sandbox connection ${c.name}?`) && act(async () => { await api.deleteSandboxConnection(c.id); sbxQ.reload(); }, `deleted sandbox connection ${c.name}`);
  const kill = (id: number, ext: string) => window.confirm(`kill sandbox ${ext}?`) && act(async () => { await api.killSandboxInstance(id); instQ.reload(); }, `killed ${ext}`);

  return (
    <div className="screen" style={{ gap: 28 }}>
      <div>
        <div className="head" style={{ marginBottom: 12 }}>
          <div>
            <h1>builds</h1>
            <div className="sub">an agent build is a stored definition — prompt, llm connection, sandbox connection, memory preset, limits. not a live process; a build runs on a repo only once subscribed to it on the repo page.</div>
          </div>
          <button className="btn primary" onClick={() => { setEditing(null); setDrawer("build"); }}>+ new build</button>
        </div>
        <div className="box">
          <div className="thead" style={{ "--cols": BCOLS } as React.CSSProperties}>
            <span>name</span><span>llm connection</span><span>sandbox connection</span><span>memory</span><span>limits</span><span>created</span><span></span>
          </div>
          {builds.map((b) => (
            <div key={b.id} className="trow click" style={{ "--cols": BCOLS, padding: "8px 12px" } as React.CSSProperties} onClick={() => { setEditing(b); setDrawer("build"); }}>
              <span>
                <b>{b.name}</b>
                <div className="small muted pretty">{b.prompt || "no prompt"}</div>
              </span>
              <span className="comment ellip">{llmName(b.llmConnectionId)}</span>
              <span className="comment ellip">{sbxName(b.sandboxConnectionId)}</span>
              <span className="comment">{b.memoryPreset ?? "—"}</span>
              <span className="comment small">{limitsText(b.limits)}</span>
              <span className="muted small">{ago(b.createdAt)}</span>
              <span className="row" style={{ flexWrap: "nowrap" }} onClick={(e) => e.stopPropagation()}>
                <button className="btn sm danger" disabled={busy} onClick={() => removeBuild(b)}>delete</button>
              </span>
            </div>
          ))}
          {builds.length === 0 && (
            <div className="empty pretty">
              {buildsQ.loading ? "loading…" : llms.length === 0 && !llmQ.loading ? "no builds — add an llm connection below first, then create a build." : "no builds — create one and subscribe it to a repository."}
            </div>
          )}
        </div>
      </div>

      <div className="grid2" style={{ gap: 16 }}>
        <div>
          <div className="head" style={{ marginBottom: 12 }}>
            <div><h2>llm connections</h2><div className="sub">openai-compatible endpoint + model; only the key mask ever crosses the wire.</div></div>
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
            <div><h2>sandbox connections</h2><div className="sub pretty">where and from which image the hub creates a sandbox instance for each agent (opensandbox endpoint + image). a build points at one connection, never at an instance.</div></div>
            <button className="btn" onClick={() => setDrawer("sbx")}>+ add</button>
          </div>
          <div className="box">
            {sbxs.map((c) => (
              <div key={c.id} className="lrow">
                <div>
                  <b>{c.name}</b> <span className="muted">· {c.image || "default image"}</span>
                  <div className="small comment">{c.domain} · key {c.apiKeyMasked ?? "—"}</div>
                </div>
                <button className="btn sm danger" disabled={busy} onClick={() => removeSbx(c)}>delete</button>
              </div>
            ))}
            {sbxs.length === 0 && <div className="empty small">{sbxQ.loading ? "loading…" : "none."}</div>}
          </div>
        </div>
      </div>

      <div className="grid2" style={{ gap: 16 }}>
        <div>
          <h2 style={{ marginBottom: 12 }}>sandbox instances <span className="muted small" style={{ fontWeight: 400 }}>· live containers, created automatically per agent on run · no ttl — killed only on command</span></h2>
          <div className="box">
            {sbxInst.filter((s) => showDead || s.status === "alive").map((s) => {
              const alive = s.status === "alive";
              const usedBy = agents.filter((a) => a.sandboxInstanceId === s.id).map((a) => `#${a.id}`);
              return (
                <div key={s.id} className="lrow" style={{ alignItems: "center" }}>
                  <div>
                    <Dot on={alive} /><b>{s.externalId}</b> <span className="muted">· {sbxName(s.sandboxConnectionId)} · {s.status}</span>
                    <div className="small comment">created {ago(s.createdAt)}{s.killedAt ? ` · killed ${ago(s.killedAt)}` : ""} · {usedBy.length ? `agent ${usedBy.join(", ")}` : "not bound to an agent"}</div>
                  </div>
                  {alive && <button className="btn sm danger" disabled={busy} onClick={() => kill(s.id, s.externalId)}>kill</button>}
                </div>
              );
            })}
            {sbxInst.filter((s) => showDead || s.status === "alive").length === 0 && <div className="empty small" style={{ padding: 12 }}>{instQ.loading ? "loading…" : "no live sandbox instances — one appears when an agent runs."}</div>}
            {sbxInst.some((s) => s.status === "dead") && (
              <button className="btn xs" style={{ margin: 8 }} onClick={() => setShowDead((v) => !v)}>{showDead ? "hide" : "show"} {sbxInst.filter((s) => s.status === "dead").length} dead</button>
            )}
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

      <BuildDrawer open={drawer === "build"} build={editing} llms={llms} sandboxes={sbxs} first={builds.length === 0} onClose={() => setDrawer(null)} reload={buildsQ.reload} />
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

function BuildDrawer({ open, build, llms, sandboxes, first, onClose, reload }: { open: boolean; build: AgentBuild | null; llms: LlmConnection[]; sandboxes: SandboxConnection[]; first: boolean; onClose: () => void; reload: () => void }) {
  const api = useHubApi();
  const { say, fail } = useShell();
  const dflt = useDefaults().data;
  const [f, setF] = useState({ name: "", llm: "", sbx: "", prompt: "", memory: "" });
  const [lim, setLim] = useState<Record<string, string>>({});
  // unknown keys of an existing limits object are kept as-is, never dropped
  const [extra, setExtra] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [seeded, setSeeded] = useState<number | null | undefined>(undefined);

  // seed form state when the drawer opens for a different build (or create)
  const seedKey = build?.id ?? null;
  if (open && seeded !== seedKey) {
    setSeeded(seedKey);
    // new build: prefilled name and default limits
    setF({ name: build?.name ?? (first ? "reviewer" : ""), llm: build?.llmConnectionId != null ? String(build.llmConnectionId) : "", sbx: build?.sandboxConnectionId != null ? String(build.sandboxConnectionId) : "", prompt: build?.prompt ?? "", memory: build?.memoryPreset ?? "" });
    const vals: Record<string, string> = {};
    if (!build) for (const [k, v] of Object.entries(dflt?.limits ?? {})) vals[k] = String(v);
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
      const input = { name: f.name.trim(), llmConnectionId: f.llm ? Number(f.llm) : undefined, sandboxConnectionId: f.sbx ? Number(f.sbx) : undefined, prompt: f.prompt.trim() || null, memoryPreset: f.memory.trim() || null, limits };
      if (build) await api.updateBuild(build.id, input);
      else await api.createBuild(input);
      say(`${build ? "saved" : "created"} build ${input.name}`);
      reload();
      onClose();
    } catch (e) {
      fail(e, "save failed");
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
            <option value="">{llms[0] ? `${llms[0].name} (first — default)` : "none — add an llm connection first"}</option>
            {llms.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
          </select>
        </Field>
        <Field label="sandbox connection · where the agent's sandbox instance is created">
          <select className="select" value={f.sbx} onChange={(e) => setF({ ...f, sbx: e.target.value })}>
            <option value="">{sandboxes[0] ? `${sandboxes[0].name} (first — default)` : "none — add a sandbox connection first"}</option>
            {sandboxes.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
          </select>
        </Field>
      </div>
      <Field label="memory preset · empty = production preset for the model; unknown names fail at run time"><input className="input" value={f.memory} onChange={(e) => setF({ ...f, memory: e.target.value })} placeholder="prod_v2" /></Field>
      <div className="flabel">limits · empty = default (3 subagents · 6 total · no budget · 600s · 300s)</div>
      <div className="grid3">
        {LIMIT_FIELDS.map((x) => (
          <Field key={x.key} label={x.label}><input className="input" type="number" value={lim[x.key] ?? ""} onChange={(e) => setLim({ ...lim, [x.key]: e.target.value })} placeholder={x.ph} /></Field>
        ))}
      </div>
      <button className="btn lg primary" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={submit}>❯ {build ? "save build" : "create build"}</button>
    </Drawer>
  );
}

function LlmDrawer({ open, onClose, reload }: { open: boolean; onClose: () => void; reload: () => void }) {
  const api = useHubApi();
  const { say, fail } = useShell();
  const dflt = useDefaults().data;
  // undefined = not touched → the hub default is shown and sent
  const [f, setF] = useState<{ name?: string; base?: string; model?: string; key: string }>({ key: "" });
  const v = { name: f.name ?? (dflt?.llmModel || "default"), base: f.base ?? dflt?.llmApiBase ?? "", model: f.model ?? dflt?.llmModel ?? "" };
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!v.name.trim() || !f.key) return fail(new Error("name and api key are required"), "");
    setBusy(true);
    try {
      await api.createLlmConnection({ name: v.name.trim(), apiBase: v.base.trim(), apiKey: f.key, model: v.model.trim() });
      say(`added llm connection ${v.name.trim()}`);
      setF({ key: "" });
      reload();
      onClose();
    } catch (e) {
      fail(e, "create failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Drawer open={open} title="new llm connection" onClose={onClose}>
      <Field label="name"><input className="input" value={v.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="openrouter" /></Field>
      <Field label="api base · prefilled from LLM_API_BASE in .env"><input className="input" value={v.base} onChange={(e) => setF({ ...f, base: e.target.value })} placeholder="https://openrouter.ai/api/v1" /></Field>
      <Field label="model · prefilled from LLM_MODEL in .env"><input className="input" value={v.model} onChange={(e) => setF({ ...f, model: e.target.value })} placeholder="anthropic/claude-sonnet-4" /></Field>
      <Field label="api key · stored masked, never returned"><input className="input" type="password" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} placeholder="sk-…" /></Field>
      <button className="btn lg primary" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={submit}>❯ add connection</button>
    </Drawer>
  );
}

function SbxDrawer({ open, onClose, reload }: { open: boolean; onClose: () => void; reload: () => void }) {
  const api = useHubApi();
  const { say, fail } = useShell();
  const dflt = useDefaults().data;
  // undefined = not touched → the hub default is shown and sent
  const [f, setF] = useState<{ name?: string; domain?: string; image?: string; key: string }>({ key: "" });
  const v = { name: f.name ?? "local-opensandbox", domain: f.domain ?? dflt?.sandboxDomain ?? "", image: f.image ?? dflt?.sandboxImage ?? "" };
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!v.name.trim()) return fail(new Error("name is required"), "");
    setBusy(true);
    try {
      await api.createSandboxConnection({ name: v.name.trim(), domain: v.domain.trim(), apiKey: f.key.trim() || undefined, image: v.image.trim() || undefined });
      say(`added sandbox connection ${v.name.trim()}`);
      setF({ key: "" });
      reload();
      onClose();
    } catch (e) {
      fail(e, "create failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Drawer open={open} title="new sandbox connection" onClose={onClose}>
      <div className="small comment pretty">an opensandbox endpoint and the image to start. the hub creates one sandbox instance (live container) per agent from it, automatically, on the first run.</div>
      <Field label="name"><input className="input" value={v.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="local-opensandbox" /></Field>
      <Field label="domain · prefilled from OPENSANDBOX_DOMAIN in .env"><input className="input" value={v.domain} onChange={(e) => setF({ ...f, domain: e.target.value })} placeholder="localhost:8090" /></Field>
      <Field label="image · prefilled from SANDBOX_IMAGE in .env"><input className="input" value={v.image} onChange={(e) => setF({ ...f, image: e.target.value })} placeholder="git-agent/sandbox:strix" /></Field>
      <Field label={`api key · empty = OPENSANDBOX_API_KEY from .env${dflt?.sandboxApiKeySet ? " (set)" : " (not set)"}`}><input className="input" type="password" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} placeholder={dflt?.sandboxApiKeySet ? "leave empty to use .env key" : ""} /></Field>
      <button className="btn lg primary" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={submit}>❯ add connection</button>
    </Drawer>
  );
}
