/** Sandboxes list — isolated environments for repo operations. A sandbox lives
 *  at most one run, so there is no live status here; just a spec registry with a
 *  create drawer whose extra field switches on kind. */
import { useState } from "react";
import { useApi } from "@/api";
import type { SandboxKind, SandboxSpec } from "@/api";
import { useSandboxes } from "@/hooks";
import { Badge, Button, Drawer, EntityList, KeyValueList, TextInput } from "@/components/primitives";
import type { Column } from "@/components/primitives";
import type { Tone } from "@/lib/tone.ts";
import styles from "./SandboxesScreen.module.css";

const KIND_TONE: Record<SandboxKind, Tone> = {
  opensandbox: "blue",
  local: "amber",
  ssh: "muted",
};

function specOf(s: SandboxSpec): string {
  if (s.kind === "opensandbox") return s.image ?? "—";
  if (s.kind === "local") return s.workdir ?? "—";
  return "—";
}

export function SandboxesScreen() {
  const sandboxesQ = useSandboxes();
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<SandboxSpec | null>(null);

  const rows = sandboxesQ.data ?? [];

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
          isolated environments for repo operations. A sandbox lives at most one run (glossary), so no live status here.
        </p>

        <div className={styles.list}>
          <EntityList
            columns={columns}
            rows={rows}
            keyOf={(s) => s.id}
            onRowClick={(s) => setSelected(s)}
            empty={sandboxesQ.loading ? "loading…" : "no sandboxes"}
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
