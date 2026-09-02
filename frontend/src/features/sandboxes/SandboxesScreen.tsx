/** Sandboxes screen — two parts: the preset registry (spec catalog) and live
 *  sandbox instances. Instances are provisioned without TTL and outlive their
 *  run, so they carry an alive/dead status and can be killed by hand here. */
import { useState } from "react";
import { useApi } from "@/api";
import type { SandboxInstance, SandboxInstanceStatus, SandboxKind, SandboxSpec } from "@/api";
import { useSandboxes, useSandboxInstances } from "@/hooks";
import { Badge, Button, Drawer, EntityList, KeyValueList, TextInput } from "@/components/primitives";
import type { Column } from "@/components/primitives";
import type { Tone } from "@/lib/tone.ts";
import styles from "./SandboxesScreen.module.css";

const KIND_TONE: Record<SandboxKind, Tone> = {
  opensandbox: "blue",
  local: "amber",
  ssh: "muted",
};

const STATUS_TONE: Record<SandboxInstanceStatus, Tone> = {
  alive: "blue",
  dead: "dim",
};

function specOf(s: SandboxSpec): string {
  if (s.kind === "opensandbox") return s.image ?? "—";
  if (s.kind === "local") return s.workdir ?? "—";
  return "—";
}

function shortId(s: string): string {
  return s.length > 12 ? `${s.slice(0, 8)}…${s.slice(-3)}` : s;
}

export function SandboxesScreen() {
  const sandboxesQ = useSandboxes();
  const instancesQ = useSandboxInstances();
  const api = useApi();
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<SandboxSpec | null>(null);
  const [killing, setKilling] = useState<Set<string>>(new Set());

  const rows = sandboxesQ.data ?? [];
  const instances = instancesQ.data ?? [];

  const kill = async (inst: SandboxInstance) => {
    setKilling((k) => new Set(k).add(inst.id));
    try {
      await api.killSandboxInstance(inst.id);
      instancesQ.reload();
    } finally {
      setKilling((k) => {
        const next = new Set(k);
        next.delete(inst.id);
        return next;
      });
    }
  };

  const instanceColumns: Column<SandboxInstance>[] = [
    { id: "status", header: "STATUS", width: "0.8fr", render: (s) => <Badge tone={STATUS_TONE[s.status]}>{s.status}</Badge> },
    { id: "externalId", header: "SANDBOX ID", width: "1.4fr", render: (s) => <span style={{ color: "var(--text)", fontFamily: "var(--font-mono, monospace)", fontSize: 11 }}>{shortId(s.externalId)}</span> },
    { id: "image", header: "IMAGE", width: "1.6fr", render: (s) => <span style={{ color: "var(--muted)", fontSize: 11 }}>{s.image ?? "—"}</span> },
    { id: "run", header: "RUN", width: "0.7fr", align: "right", render: (s) => <span style={{ color: "var(--amber)" }}>{s.runId ? `#${s.runId}` : "—"}</span> },
    {
      id: "action",
      header: "",
      width: "0.9fr",
      align: "right",
      render: (s) =>
        s.status === "alive" ? (
          <button
            type="button"
            className={styles.killBtn}
            disabled={killing.has(s.id)}
            onClick={(e) => {
              e.stopPropagation();
              kill(s);
            }}
          >
            {killing.has(s.id) ? "killing…" : "✕ kill"}
          </button>
        ) : (
          <span className={styles.dimSmall}>{s.killedAt ? "killed" : "—"}</span>
        ),
    },
  ];

  const columns: Column<SandboxSpec>[] = [
    { id: "name", header: "NAME", width: "1.4fr", render: (s) => <span style={{ color: "var(--text)" }}>{s.name}</span> },
    { id: "kind", header: "KIND", width: "0.9fr", render: (s) => <Badge tone={KIND_TONE[s.kind]}>{s.kind}</Badge> },
    { id: "spec", header: "IMAGE / WORKDIR", width: "2fr", render: (s) => <span style={{ color: "var(--muted)", fontSize: 11 }}>{specOf(s)}</span> },
    { id: "runs", header: "RUNS", width: "0.6fr", align: "right", render: (s) => <span style={{ color: "var(--amber)" }}>{s.runCount}</span> },
  ];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>sandboxes</h1>
          <span className={styles.path}>~/git-agent/sandboxes</span>
          <div style={{ flex: 1 }} />
          <Button variant="primary" onClick={() => setCreating(true)}>
            + new sandbox
          </Button>
        </div>

        <p className={styles.muted}>
          isolated environments for repo operations. Presets are the spec catalog; instances are provisioned sandboxes that live without TTL until killed.
        </p>

        <div className={styles.sectionTitle}>PRESETS</div>
        <div className={styles.list}>
          <EntityList
            columns={columns}
            rows={rows}
            keyOf={(s) => s.id}
            onRowClick={(s) => setSelected(s)}
            empty={sandboxesQ.loading ? "loading…" : "no sandboxes"}
          />
        </div>

        <div className={styles.sectionTitle}>
          INSTANCES
          <span className={styles.dimSmall}>
            {instances.filter((i) => i.status === "alive").length} alive · {instances.length} total
          </span>
        </div>
        <div className={styles.list}>
          <EntityList
            columns={instanceColumns}
            rows={instances}
            keyOf={(s) => s.id}
            empty={instancesQ.loading ? "loading…" : "no instances"}
          />
        </div>
      </div>

      <Drawer open={selected != null} title="◆ sandbox" onClose={() => setSelected(null)} width={460}>
        {selected && (
          <KeyValueList
            rows={[
              { key: "id", value: selected.id },
              { key: "name", value: selected.name, tone: "text" },
              { key: "kind", value: selected.kind, tone: KIND_TONE[selected.kind] },
              { key: "image", value: selected.image ?? "—" },
              { key: "workdir", value: selected.workdir ?? "—" },
              { key: "created", value: selected.createdAt },
              { key: "run count", value: selected.runCount, tone: "amber" },
            ]}
          />
        )}
      </Drawer>

      <CreateDrawer open={creating} onClose={() => setCreating(false)} onCreated={() => sandboxesQ.reload()} />
    </div>
  );
}

function CreateDrawer({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const api = useApi();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<SandboxKind>("opensandbox");
  const [image, setImage] = useState("");
  const [workdir, setWorkdir] = useState("");
  const [busy, setBusy] = useState(false);

  const isSsh = kind === "ssh";
  const canSubmit = !!name.trim() && !isSsh && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    try {
      await api.createSandbox({
        name: name.trim(),
        kind,
        image: kind === "opensandbox" ? image.trim() || undefined : undefined,
        workdir: kind === "local" ? workdir.trim() || undefined : undefined,
      });
      onCreated();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open={open} title="◆ new sandbox" onClose={onClose} width={460}>
      <label className={styles.label}>NAME</label>
      <TextInput
        value={name}
        active={!!name.trim()}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder="python"
      />

      <label className={styles.label}>KIND</label>
      <select className={styles.select} value={kind} onChange={(e) => setKind(e.target.value as SandboxKind)}>
        <option value="opensandbox">opensandbox</option>
        <option value="local">local</option>
        <option value="ssh">ssh</option>
      </select>

      {kind === "opensandbox" && (
        <>
          <label className={styles.label}>IMAGE</label>
          <TextInput
            value={image}
            onChange={(e) => setImage(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="python:3.13-slim"
          />
        </>
      )}

      {kind === "local" && (
        <>
          <label className={styles.label}>WORKDIR</label>
          <TextInput
            value={workdir}
            onChange={(e) => setWorkdir(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="/workspace/repo"
          />
        </>
      )}

      {isSsh && (
        <>
          <label className={styles.label}>SSH</label>
          <TextInput disabled value="" placeholder="—" />
          <div className={styles.notice}>
            <Badge tone="crit" outline>
              not implemented
            </Badge>
            ssh kind is declared but not implemented in the backend (NotImplementedError)
          </div>
        </>
      )}

      <div className={styles.actions}>
        <Button variant="primary" disabled={!canSubmit} onClick={submit}>
          + create
        </Button>
        <Button variant="ghost" onClick={onClose}>
          cancel
        </Button>
      </div>
    </Drawer>
  );
}
