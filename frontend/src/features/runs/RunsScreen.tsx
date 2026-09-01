/** Runs list — the home surface. Status filters ("reports" = succeeded), and a
 *  submit drawer that handles all four idempotency dispositions honestly. */
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useApi, DEFAULT_RUN_FEATURES } from "@/api";
import type { Run, RunFeatures, RunStatus, SubmitDisposition, SubmitRunRequest } from "@/api";
import { useConnections, useMemoryPresets, useRuns, useSandboxes } from "@/hooks";
import { Badge, Button, Drawer, EntityList, StatusBadge, TextInput } from "@/components/primitives";
import type { Column } from "@/components/primitives";
import { elapsed, tokensLabel } from "@/lib/format.ts";
import { RUN_STATUS_ORDER } from "@/lib/status.ts";
import styles from "./runs-list.module.css";

type Filter = "all" | RunStatus | "reports";

export function RunsScreen() {
  const navigate = useNavigate();
  const api = useApi();
  const runsQ = useRuns();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<Filter>("all");

  const drawerOpen = params.get("new") === "1";
  const openDrawer = () => setParams({ new: "1" });
  const closeDrawer = () => setParams({});

  const runs = runsQ.data ?? [];
  const filtered = useMemo(() => {
    if (filter === "all") return runs;
    if (filter === "reports") return runs.filter((r) => r.status === "succeeded");
    return runs.filter((r) => r.status === filter);
  }, [runs, filter]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: runs.length, reports: runs.filter((r) => r.status === "succeeded").length };
    RUN_STATUS_ORDER.forEach((s) => (c[s] = runs.filter((r) => r.status === s).length));
    return c;
  }, [runs]);

  const columns: Column<Run>[] = [
    {
      id: "repo",
      header: "REPOSITORY",
      width: "2.2fr",
      render: (r) => (
        <div style={{ minWidth: 0 }}>
          <div style={{ color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis" }}>{r.repo}</div>
          <div style={{ fontSize: 11, color: "var(--dim)" }}>{r.commitSha?.slice(0, 7) ?? "—"}</div>
        </div>
      ),
    },
    { id: "status", header: "STATUS", width: "1fr", render: (r) => <StatusBadge status={r.status} /> },
    { id: "attempt", header: "ATTEMPT", width: "0.7fr", render: (r) => <span style={{ color: "var(--muted)" }}>{r.attempt}</span> },
    { id: "model", header: "MODEL", width: "1.1fr", render: (r) => <span style={{ color: "var(--muted)", fontSize: 11 }}>{r.connection.model}</span> },
    { id: "sandbox", header: "SANDBOX", width: "0.9fr", render: (r) => <span style={{ color: "var(--muted)", fontSize: 11 }}>{r.sandbox ?? "—"}</span> },
    { id: "elapsed", header: "ELAPSED", width: "0.7fr", render: (r) => <span style={{ color: "var(--amber)" }}>{elapsed(r.metrics.elapsedSec)}</span> },
    {
      id: "tokens",
      header: "TOKENS",
      width: "0.7fr",
      align: "right",
      render: (r) => (
        <span style={{ color: r.metrics.tokenUsage ? "var(--text)" : "var(--dim)" }}>
          {r.metrics.tokenUsage ? tokensLabel(r.metrics.tokenUsage.totalTokens) : "—"}
        </span>
      ),
    },
    {
      id: "del",
      header: "",
      width: "28px",
      align: "right",
      render: (r) =>
        r.status === "running" || r.status === "pending" ? null : (
          <span
            title="delete run"
            style={{ color: "var(--dim)", cursor: "pointer" }}
            onClick={async (e) => {
              e.stopPropagation();
              await api.deleteRun(r.id);
              runsQ.reload();
            }}
          >
            ✕
          </span>
        ),
    },
    { id: "go", header: "", width: "40px", align: "right", render: () => <span style={{ color: "var(--amber)" }}>→</span> },
  ];

  const filters: Filter[] = ["all", "running", "pending", "succeeded", "interrupted", "failed", "reports"];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>runs</h1>
          <span className={styles.path}>~/git-agent/runs</span>
          <div style={{ flex: 1 }} />
          <Button variant="primary" onClick={openDrawer}>
            ❯ new run
          </Button>
        </div>

        <div className={styles.filters}>
          {filters.map((f) => (
            <span
              key={f}
              className={[styles.filter, filter === f ? styles.filterOn : ""].join(" ")}
              onClick={() => setFilter(f)}
            >
              {f} {counts[f] ?? 0}
            </span>
          ))}
        </div>

        <div className={styles.list}>
          <EntityList
            columns={columns}
            rows={filtered}
            keyOf={(r) => r.id}
            onRowClick={(r) => navigate(`/runs/${r.id}`)}
            empty={runsQ.loading ? "loading…" : "no runs"}
          />
        </div>
      </div>

      <SubmitDrawer
        open={drawerOpen}
        onClose={closeDrawer}
        onSubmitted={(run, disposition) => {
          closeDrawer();
          navigate(`/runs/${run.id}`, { state: { disposition } });
        }}
      />
    </div>
  );
}

function SubmitDrawer({
  open,
  onClose,
  onSubmitted,
}: {
  open: boolean;
  onClose: () => void;
  onSubmitted: (run: Run, disposition: SubmitDisposition) => void;
}) {
  const api = useApi();
  const conns = useConnections();
  const sandboxes = useSandboxes();
  const presets = useMemoryPresets();

  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [mode, setMode] = useState<"pipeline" | "agent">("agent");
  const [instructions, setInstructions] = useState("");
  const [connMode, setConnMode] = useState<"saved" | "custom">("saved");
  const [connectionId, setConnectionId] = useState<string>("");
  const [apiBase, setApiBase] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  // git — единственная песочница с git в образе; python:3.12-slim клонить не может
  const [sandbox, setSandbox] = useState<string>("git");
  const [memoryPreset, setMemoryPreset] = useState<string>("prod_v2");
  const [features, setFeatures] = useState<RunFeatures>(DEFAULT_RUN_FEATURES);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const patchFeatures = (p: Partial<RunFeatures>) => setFeatures((f) => ({ ...f, ...p }));
  const customValid = connMode === "saved" || (apiBase.trim() !== "" && model.trim() !== "");
  const canSubmit = repoUrl.trim() !== "" && customValid && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setNotice(null);
    const req: SubmitRunRequest = {
      repoUrl,
      branch: branch.trim() || undefined,
      mode,
      instructions: instructions.trim() || undefined,
      sandbox,
      memoryPreset,
      features,
    };
    if (connMode === "saved") req.connectionId = connectionId || undefined;
    else {
      req.apiBase = apiBase.trim();
      req.apiKey = apiKey || undefined;
      req.model = model.trim();
    }
    try {
      const res = await api.submitRun(req);
      if (res.disposition !== "created") {
        setNotice(dispositionNote(res.disposition));
        setTimeout(() => onSubmitted(res.run, res.disposition), 900);
      } else {
        onSubmitted(res.run, res.disposition);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open={open} title="◆ new run · configure" onClose={onClose} width={480}>
      <div className={styles.group}>repository</div>
      <label className={styles.label}>REPOSITORY URL</label>
      <TextInput
        value={repoUrl}
        active={!!repoUrl.trim()}
        onChange={(e) => setRepoUrl(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder="github.com/org/repository"
      />
      <label className={styles.label}>BRANCH</label>
      <TextInput glyph="⎇" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" />
      <label className={styles.label}>MODE</label>
      <div className={styles.segmented}>
        {(["agent", "pipeline"] as const).map((m) => (
          <span
            key={m}
            className={[styles.seg, mode === m ? styles.segOn : ""].join(" ")}
            onClick={() => setMode(m)}
          >
            {m === "agent" ? "agent · lead + subagents" : "pipeline · scan→parse→report"}
          </span>
        ))}
      </div>
      <label className={styles.label}>TASK / INSTRUCTIONS</label>
      <textarea
        className={styles.select}
        rows={3}
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
        placeholder="дефолтная задача агента; {repo_url} подставляется"
      />

      <div className={styles.group}>model &amp; connection</div>
      <div className={styles.segmented}>
        {(["saved", "custom"] as const).map((m) => (
          <span
            key={m}
            className={[styles.seg, connMode === m ? styles.segOn : ""].join(" ")}
            onClick={() => setConnMode(m)}
          >
            {m === "saved" ? "saved connection" : "custom endpoint"}
          </span>
        ))}
      </div>
      {connMode === "saved" ? (
        <>
          <label className={styles.label}>CONNECTION</label>
          <select className={styles.select} value={connectionId} onChange={(e) => setConnectionId(e.target.value)}>
            <option value="">— backend default —</option>
            {(conns.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.model}
              </option>
            ))}
          </select>
        </>
      ) : (
        <>
          <label className={styles.label}>API BASE</label>
          <TextInput glyph="›" value={apiBase} onChange={(e) => setApiBase(e.target.value)} placeholder="https://api.anthropic.com/v1" />
          <label className={styles.label}>API KEY (write-only)</label>
          <TextInput glyph="›" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-…" />
          <label className={styles.label}>MODEL</label>
          <TextInput glyph="›" value={model} onChange={(e) => setModel(e.target.value)} placeholder="claude-opus-4" />
        </>
      )}

      <div className={styles.group}>execution</div>
      <label className={styles.label}>SANDBOX</label>
      <select className={styles.select} value={sandbox} onChange={(e) => setSandbox(e.target.value)}>
        {(sandboxes.data ?? []).map((s) => (
          <option key={s.id} value={s.name}>
            {s.name} · {s.kind}
            {s.image ? ` · ${s.image}` : s.workdir ? ` · ${s.workdir}` : ""}
          </option>
        ))}
      </select>
      <label className={styles.label}>MEMORY PRESET</label>
      <select className={styles.select} value={memoryPreset} onChange={(e) => setMemoryPreset(e.target.value)}>
        {(presets.data ?? []).map((p) => (
          <option key={p.name} value={p.name}>
            {p.name}
            {p.production ? " (prod)" : ""}
          </option>
        ))}
      </select>
      <p className={styles.hint}>
        Memory preset is part of the run's experiment identity but not its uniqueness key — the same (repo, commit, model)
        submitted with a different preset attaches to the existing run rather than starting a new one.
      </p>

      <div className={styles.group} style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }} onClick={() => setShowAdvanced((v) => !v)}>
        <span>{showAdvanced ? "▾" : "▸"}</span>
        advanced · limits &amp; features
      </div>
      {showAdvanced && (
        <>
          <Toggle label="sub-agents (task tool)" tag="active" on={features.subagent} onClick={() => patchFeatures({ subagent: !features.subagent })} />
          <label className={styles.label}>MAX CONCURRENT SUB-AGENTS</label>
          <TextInput
            glyph="#"
            type="number"
            value={String(features.maxSubagents)}
            onChange={(e) => patchFeatures({ maxSubagents: Math.max(1, Number(e.target.value) || 1) })}
          />
          <label className={styles.label}>
            TOKEN BUDGET <span style={{ color: "var(--med)" }}>· planned</span>
          </label>
          <TextInput
            glyph="#"
            type="number"
            placeholder="unlimited"
            value={features.tokenBudget == null ? "" : String(features.tokenBudget)}
            onChange={(e) => {
              const v = e.target.value.trim();
              patchFeatures({ tokenBudget: v === "" ? null : Math.max(0, Number(v) || 0) });
            }}
          />
          <Toggle label="guardrail" tag="planned" disabled on={features.guardrail} onClick={() => {}} />
          <Toggle label="loop detection" tag="planned" disabled on={features.loopDetection} onClick={() => {}} />
          <p className={styles.hint}>
            <b>subagent</b> is wired today (star depth 1, general-purpose); <b>token budget</b> / <b>guardrail</b> /{" "}
            <b>loop detection</b> are declared in RuntimeFeatures but not yet wired in the backend.
          </p>
        </>
      )}

      {notice && (
        <div className={styles.notice}>
          <Badge tone="med" outline>
            idempotent
          </Badge>
          {notice}
        </div>
      )}

      <div className={styles.actions}>
        <Button variant="primary" disabled={!canSubmit} onClick={submit}>
          ▶ submit run
        </Button>
        <Button variant="ghost" onClick={onClose}>
          cancel
        </Button>
      </div>
      <p className={styles.hint}>
        Submit is idempotent per (repo, commit, model): an existing in-flight or finished run may be attached instead of a new one.
      </p>
    </Drawer>
  );
}

function Toggle({
  label,
  on,
  onClick,
  tag,
  disabled,
}: {
  label: string;
  on: boolean;
  onClick: () => void;
  tag?: "active" | "planned";
  disabled?: boolean;
}) {
  return (
    <div
      className={styles.toggle}
      style={{ opacity: disabled ? 0.55 : 1, cursor: disabled ? "not-allowed" : "pointer" }}
      onClick={disabled ? undefined : onClick}
    >
      <span style={{ color: on ? "var(--low)" : "var(--dim)" }}>{on ? "●" : "○"}</span>
      <span className={styles.toggleLabel}>{label}</span>
      {tag && (
        <Badge tone={tag === "active" ? "low" : "med"} outline>
          {tag}
        </Badge>
      )}
    </div>
  );
}

function dispositionNote(d: SubmitDisposition): string {
  switch (d) {
    case "attached":
      return "a run for this repo is already in flight — attaching to it.";
    case "already_succeeded":
      return "this repo+commit+model already succeeded — opening the existing report.";
    case "resumed":
      return "resuming a previously failed/interrupted run.";
    default:
      return "";
  }
}
