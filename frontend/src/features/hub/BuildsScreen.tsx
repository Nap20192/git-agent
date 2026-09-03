/** Сборки Агентов (stored agent definitions) + the connections they reference.
 *  A build = llm + sandbox connection + prompt + memory preset + limits. */
import { useState } from "react";
import { useHubApi, type AgentBuild, type LlmConnection, type SandboxConnection } from "@/api/hub";
import { useBuilds, useLlmConnections, useSandboxConnections } from "@/hooks";
import { Badge, Button, Drawer, EntityList, Panel, PanelHeader, TextInput } from "@/components/primitives";
import type { Column } from "@/components/primitives";
import styles from "./hub.module.css";

export function BuildsScreen() {
  const buildsQ = useBuilds();
  const llmQ = useLlmConnections();
  const sandboxQ = useSandboxConnections();
  const [editing, setEditing] = useState<AgentBuild | null>(null);
  const [creating, setCreating] = useState(false);

  const llms = llmQ.data ?? [];
  const sandboxes = sandboxQ.data ?? [];
  const llmName = (id?: number) => llms.find((c) => c.id === id)?.name ?? "—";
  const sandboxName = (id?: number) => sandboxes.find((c) => c.id === id)?.name ?? "—";

  const columns: Column<AgentBuild>[] = [
    {
      id: "name",
      header: "NAME",
      width: "1.4fr",
      render: (b) => (
        <span style={{ color: "var(--text)" }}>
          {b.name} {b.isDefault && <Badge tone="amber">default</Badge>}
        </span>
      ),
    },
    { id: "llm", header: "LLM", width: "1.1fr", render: (b) => <span className={styles.cell}>{llmName(b.llmConnectionId)}</span> },
    { id: "sandbox", header: "SANDBOX", width: "1.1fr", render: (b) => <span className={styles.cell}>{sandboxName(b.sandboxConnectionId)}</span> },
    { id: "preset", header: "MEMORY", width: "0.9fr", render: (b) => <span className={styles.cell}>{b.memoryPreset ?? "—"}</span> },
    {
      id: "created",
      header: "CREATED",
      width: "1.1fr",
      render: (b) => <span className={styles.cell}>{b.createdAt ? new Date(b.createdAt).toLocaleString() : "—"}</span>,
    },
  ];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>builds</h1>
          <div style={{ flex: 1 }} />
          <Button variant="primary" onClick={() => setCreating(true)}>
            + new build
          </Button>
        </div>
        <p className={styles.blurb}>
          Сборка Агента — a stored agent definition, not a live process. Repositories bind to one build; its
          Экземпляр runs with these connections and limits.
        </p>

        <div className={styles.list}>
          <EntityList
            columns={columns}
            rows={buildsQ.data ?? []}
            keyOf={(b) => String(b.id)}
            onRowClick={setEditing}
            empty={buildsQ.loading ? "loading…" : "no builds"}
          />
        </div>

        <div className={styles.section}>
          <ConnectionsPanels llmQ={llmQ} sandboxQ={sandboxQ} />
        </div>
      </div>

      <BuildDrawer
        open={creating || editing != null}
        build={editing}
        llms={llms}
        sandboxes={sandboxes}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
        reload={buildsQ.reload}
      />
    </div>
  );
}

function BuildDrawer({
  open,
  build,
  llms,
  sandboxes,
  onClose,
  reload,
}: {
  open: boolean;
  build: AgentBuild | null;
  llms: LlmConnection[];
  sandboxes: SandboxConnection[];
  onClose: () => void;
  reload: () => void;
}) {
  const api = useHubApi();
  const [name, setName] = useState("");
  const [llmId, setLlmId] = useState("");
  const [sandboxId, setSandboxId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [preset, setPreset] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [busy, setBusy] = useState(false);
  const [seeded, setSeeded] = useState<number | null | undefined>(undefined);

  // Seed form state when the drawer opens for a different build (or create).
  const seedKey = build?.id ?? null;
  if (open && seeded !== seedKey) {
    setSeeded(seedKey);
    setName(build?.name ?? "");
    setLlmId(build?.llmConnectionId != null ? String(build.llmConnectionId) : "");
    setSandboxId(build?.sandboxConnectionId != null ? String(build.sandboxConnectionId) : "");
    setPrompt(build?.prompt ?? "");
    setPreset(build?.memoryPreset ?? "");
    setIsDefault(build?.isDefault ?? false);
  }
  if (!open && seeded !== undefined) setSeeded(undefined);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const input = {
        name: name.trim(),
        llmConnectionId: llmId ? Number(llmId) : undefined,
        sandboxConnectionId: sandboxId ? Number(sandboxId) : undefined,
        prompt: prompt.trim() || null,
        memoryPreset: preset.trim() || null,
        isDefault,
      };
      if (build) await api.updateBuild(build.id, input);
      else await api.createBuild(input);
      reload();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!build) return;
    setBusy(true);
    try {
      await api.deleteBuild(build.id);
      reload();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open={open} title={build ? `◆ ${build.name}` : "◆ new build"} onClose={onClose} width={460}>
      <label className={styles.label}>NAME</label>
      <TextInput value={name} active={!!name.trim()} onChange={(e) => setName(e.target.value)} placeholder="security-reviewer" />

      <label className={styles.label}>LLM CONNECTION</label>
      <select className={styles.select} value={llmId} onChange={(e) => setLlmId(e.target.value)}>
        <option value="">—</option>
        {llms.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name} ({c.model})
          </option>
        ))}
      </select>

      <label className={styles.label}>SANDBOX CONNECTION</label>
      <select className={styles.select} value={sandboxId} onChange={(e) => setSandboxId(e.target.value)}>
        <option value="">—</option>
        {sandboxes.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name} ({c.domain})
          </option>
        ))}
      </select>

      <label className={styles.label}>PROMPT</label>
      <textarea
        className={styles.textarea}
        rows={4}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="what should this agent watch for…"
      />

      <label className={styles.label}>MEMORY PRESET</label>
      <TextInput value={preset} onChange={(e) => setPreset(e.target.value)} placeholder="prod_v2" />

      <label className={styles.check}>
        <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
        default build for newly connected repositories
      </label>

      <div className={styles.actions}>
        <Button variant="primary" disabled={busy || !name.trim()} onClick={submit}>
          {build ? "save" : "▶ create"}
        </Button>
        {build && (
          <Button variant="ghost" disabled={busy} onClick={remove}>
            delete
          </Button>
        )}
        <Button variant="ghost" onClick={onClose}>
          cancel
        </Button>
      </div>
    </Drawer>
  );
}

/* ── connections (llm | sandbox), keys arrive masked ─────────────────── */

function ConnectionsPanels({
  llmQ,
  sandboxQ,
}: {
  llmQ: ReturnType<typeof useLlmConnections>;
  sandboxQ: ReturnType<typeof useSandboxConnections>;
}) {
  const api = useHubApi();
  const [llmForm, setLlmForm] = useState(false);
  const [sandboxForm, setSandboxForm] = useState(false);

  const llmColumns: Column<LlmConnection>[] = [
    { id: "name", header: "NAME", width: "1fr", render: (c) => <span style={{ color: "var(--text)" }}>{c.name}</span> },
    { id: "model", header: "MODEL", width: "1.3fr", render: (c) => <span className={styles.cell}>{c.model}</span> },
    { id: "key", header: "KEY", width: "0.8fr", render: (c) => <span className={styles.cell}>{c.apiKeyMasked}</span> },
    {
      id: "del",
      header: "",
      width: "70px",
      align: "right",
      render: (c) => (
        <Button
          variant="ghost"
          onClick={(e) => {
            e.stopPropagation();
            api.deleteLlmConnection(c.id).then(llmQ.reload);
          }}
        >
          ✕
        </Button>
      ),
    },
  ];

  const sandboxColumns: Column<SandboxConnection>[] = [
    { id: "name", header: "NAME", width: "1fr", render: (c) => <span style={{ color: "var(--text)" }}>{c.name}</span> },
    { id: "domain", header: "DOMAIN", width: "1.3fr", render: (c) => <span className={styles.cell}>{c.domain}</span> },
    { id: "key", header: "KEY", width: "0.8fr", render: (c) => <span className={styles.cell}>{c.apiKeyMasked ?? "—"}</span> },
    {
      id: "del",
      header: "",
      width: "70px",
      align: "right",
      render: (c) => (
        <Button
          variant="ghost"
          onClick={(e) => {
            e.stopPropagation();
            api.deleteSandboxConnection(c.id).then(sandboxQ.reload);
          }}
        >
          ✕
        </Button>
      ),
    },
  ];

  return (
    <div className={styles.detailGrid}>
      <Panel>
        <PanelHeader icon="⚡" title="LLM CONNECTIONS" right={<Button variant="ghost" onClick={() => setLlmForm(true)}>+ add</Button>} />
        <EntityList columns={llmColumns} rows={llmQ.data ?? []} keyOf={(c) => String(c.id)} empty="no llm connections" />
      </Panel>
      <Panel>
        <PanelHeader icon="▣" title="SANDBOX CONNECTIONS" right={<Button variant="ghost" onClick={() => setSandboxForm(true)}>+ add</Button>} />
        <EntityList columns={sandboxColumns} rows={sandboxQ.data ?? []} keyOf={(c) => String(c.id)} empty="no sandbox connections" />
      </Panel>

      <LlmConnectionDrawer open={llmForm} onClose={() => setLlmForm(false)} reload={llmQ.reload} />
      <SandboxConnectionDrawer open={sandboxForm} onClose={() => setSandboxForm(false)} reload={sandboxQ.reload} />
    </div>
  );
}

function LlmConnectionDrawer({ open, onClose, reload }: { open: boolean; onClose: () => void; reload: () => void }) {
  const api = useHubApi();
  const [name, setName] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = name.trim() && apiBase.trim() && apiKey.trim() && model.trim();

  const submit = async () => {
    if (!valid) return;
    setBusy(true);
    try {
      await api.createLlmConnection({ name, apiBase, apiKey, model });
      reload();
      setName(""); setApiBase(""); setApiKey(""); setModel("");
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open={open} title="◆ new llm connection" onClose={onClose} width={460}>
      <label className={styles.label}>NAME</label>
      <TextInput value={name} active={!!name.trim()} onChange={(e) => setName(e.target.value)} placeholder="my-endpoint" />
      <label className={styles.label}>API BASE</label>
      <TextInput value={apiBase} active={!!apiBase.trim()} onChange={(e) => setApiBase(e.target.value)} placeholder="https://api.openai.com/v1" />
      <label className={styles.label}>
        API KEY <span className={styles.note}>— write-only, returned masked</span>
      </label>
      <TextInput value={apiKey} type="password" onChange={(e) => setApiKey(e.target.value)} placeholder="sk-…" />
      <label className={styles.label}>MODEL</label>
      <TextInput value={model} active={!!model.trim()} onChange={(e) => setModel(e.target.value)} placeholder="claude-sonnet-4" />
      <div className={styles.actions}>
        <Button variant="primary" disabled={!valid || busy} onClick={submit}>▶ create</Button>
        <Button variant="ghost" onClick={onClose}>cancel</Button>
      </div>
    </Drawer>
  );
}

function SandboxConnectionDrawer({ open, onClose, reload }: { open: boolean; onClose: () => void; reload: () => void }) {
  const api = useHubApi();
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [image, setImage] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = name.trim() && domain.trim();

  const submit = async () => {
    if (!valid) return;
    setBusy(true);
    try {
      await api.createSandboxConnection({
        name,
        domain,
        apiKey: apiKey.trim() || undefined,
        image: image.trim() || undefined,
      });
      reload();
      setName(""); setDomain(""); setApiKey(""); setImage("");
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open={open} title="◆ new sandbox connection" onClose={onClose} width={460}>
      <label className={styles.label}>NAME</label>
      <TextInput value={name} active={!!name.trim()} onChange={(e) => setName(e.target.value)} placeholder="local-opensandbox" />
      <label className={styles.label}>DOMAIN</label>
      <TextInput value={domain} active={!!domain.trim()} onChange={(e) => setDomain(e.target.value)} placeholder="http://localhost:8090" />
      <label className={styles.label}>
        API KEY <span className={styles.note}>— optional, write-only</span>
      </label>
      <TextInput value={apiKey} type="password" onChange={(e) => setApiKey(e.target.value)} placeholder="dev-local-key" />
      <label className={styles.label}>IMAGE</label>
      <TextInput value={image} onChange={(e) => setImage(e.target.value)} placeholder="opensandbox/base" />
      <div className={styles.actions}>
        <Button variant="primary" disabled={!valid || busy} onClick={submit}>▶ create</Button>
        <Button variant="ghost" onClick={onClose}>cancel</Button>
      </div>
    </Drawer>
  );
}
