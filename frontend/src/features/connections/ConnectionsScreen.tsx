/** Connections list — named LLM endpoints. Detail + create drawers; keys are
 *  write-only (only the mask is stored). */
import { useState } from "react";
import { useApi } from "@/api";
import type { Connection } from "@/api";
import { useConnections } from "@/hooks";
import { Button, Drawer, EntityList, KeyValueList, StatusDot, TextInput } from "@/components/primitives";
import type { Column } from "@/components/primitives";
import type { Tone } from "@/lib/tone.ts";
import styles from "./ConnectionsScreen.module.css";

function hostOf(apiBase: string): string {
  try {
    return new URL(apiBase).host;
  } catch {
    return apiBase;
  }
}

function reachability(c: Connection): { tone: Tone; text: string } {
  if (c.lastCheck) {
    return c.lastCheck.ok
      ? { tone: "low", text: `ok ${c.lastCheck.latencyMs}ms` }
      : { tone: "crit", text: "failed" };
  }
  return { tone: "dim", text: "unchecked" };
}

export function ConnectionsScreen() {
  const connsQ = useConnections();
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Connection | null>(null);

  const rows = connsQ.data ?? [];

  const columns: Column<Connection>[] = [
    { id: "name", header: "NAME", width: "1.4fr", render: (c) => <span style={{ color: "var(--text)" }}>{c.name}</span> },
    { id: "host", header: "API BASE", width: "1.6fr", render: (c) => <span style={{ color: "var(--muted)", fontSize: 11 }}>{hostOf(c.apiBase)}</span> },
    { id: "model", header: "MODEL", width: "1.4fr", render: (c) => <span style={{ color: "var(--muted)", fontSize: 11 }}>{c.model}</span> },
    { id: "key", header: "KEY", width: "1fr", render: (c) => <span style={{ color: "var(--dim)", fontSize: 11 }}>{c.keyMasked}</span> },
    {
      id: "reach",
      header: "REACHABILITY",
      width: "1.2fr",
      render: (c) => {
        const r = reachability(c);
        return (
          <span className={styles.reach}>
            <StatusDot tone={r.tone} />
            <span style={{ fontSize: 11, color: "var(--muted)" }}>{r.text}</span>
          </span>
        );
      },
    },
  ];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>connections</h1>
          <div style={{ flex: 1 }} />
          <Button variant="primary" onClick={() => setCreating(true)}>
            + new connection
          </Button>
        </div>
        <p className={styles.blurb}>
          named LLM endpoints (api_base + key + model). Keys are write-only — only the mask is stored.
        </p>

        <div className={styles.list}>
          <EntityList
            columns={columns}
            rows={rows}
            keyOf={(c) => c.id}
            onRowClick={(c) => setSelected(c)}
            empty={connsQ.loading ? "loading…" : "no connections"}
          />
        </div>
      </div>

      <DetailDrawer connection={selected} onClose={() => setSelected(null)} reload={connsQ.reload} />
      <CreateDrawer open={creating} onClose={() => setCreating(false)} reload={connsQ.reload} />
    </div>
  );
}

function DetailDrawer({
  connection,
  onClose,
  reload,
}: {
  connection: Connection | null;
  onClose: () => void;
  reload: () => void;
}) {
  const api = useApi();
  const [busy, setBusy] = useState(false);

  if (!connection) return null;

  const check = async () => {
    setBusy(true);
    try {
      await api.checkConnection(connection.id);
      reload();
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteConnection(connection.id);
      reload();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open title={`◆ ${connection.name}`} onClose={onClose} width={460}>
      <KeyValueList
        rows={[
          { key: "name", value: connection.name },
          { key: "api_base", value: connection.apiBase },
          { key: "model", value: connection.model },
          { key: "key", value: connection.keyMasked, tone: "dim" },
          { key: "created", value: new Date(connection.createdAt).toLocaleString() },
        ]}
      />
      <div className={styles.actions}>
        <Button variant="outline" disabled={busy} onClick={check}>
          check
        </Button>
        <Button variant="ghost" disabled={busy} onClick={remove}>
          delete
        </Button>
      </div>
    </Drawer>
  );
}

function CreateDrawer({ open, onClose, reload }: { open: boolean; onClose: () => void; reload: () => void }) {
  const api = useApi();
  const [name, setName] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);

  const valid = name.trim() && apiBase.trim() && model.trim();

  const submit = async () => {
    if (!valid) return;
    setBusy(true);
    try {
      await api.createConnection({ name, apiBase, apiKey, model });
      reload();
      setName("");
      setApiBase("");
      setApiKey("");
      setModel("");
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open={open} title="◆ new connection" onClose={onClose} width={460}>
      <label className={styles.label}>NAME</label>
      <TextInput value={name} active={!!name.trim()} onChange={(e) => setName(e.target.value)} placeholder="my-endpoint" />

      <label className={styles.label}>API BASE</label>
      <TextInput
        value={apiBase}
        active={!!apiBase.trim()}
        onChange={(e) => setApiBase(e.target.value)}
        placeholder="https://api.openai.com/v1"
      />

      <label className={styles.label}>
        API KEY <span className={styles.note}>— write-only</span>
      </label>
      <TextInput
        value={apiKey}
        type="password"
        onChange={(e) => setApiKey(e.target.value)}
        placeholder="sk-…"
      />

      <label className={styles.label}>MODEL</label>
      <TextInput value={model} active={!!model.trim()} onChange={(e) => setModel(e.target.value)} placeholder="gpt-4o" />

      <div className={styles.actions}>
        <Button variant="primary" disabled={!valid || busy} onClick={submit}>
          ▶ create
        </Button>
        <Button variant="ghost" onClick={onClose}>
          cancel
        </Button>
      </div>
      <p className={styles.hint}>The raw key is sent once and never returned — only its mask is stored.</p>
    </Drawer>
  );
}
