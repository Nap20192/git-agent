/** Connected repositories (hub monitors them via webhooks) + the Событие
 *  journal per repo. Connecting: pick identity → pick a provider repo →
 *  POST /api/repositories (hub installs the webhook). */
import { useState } from "react";
import { useHubApi, type AgentBuild, type Provider, type Repository } from "@/api/hub";
import { useBuilds, useHubRepositories, useIdentityRepos, useMe, useRepoEvents } from "@/hooks";
import { Badge, Button, Drawer, EntityList, KeyValueList } from "@/components/primitives";
import type { Column } from "@/components/primitives";
import type { Tone } from "@/lib/tone.ts";
import styles from "./hub.module.css";

const providerTone = (p: Provider): Tone => (p === "github" ? "text" : "burnt");

export function RepositoriesScreen() {
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const [connecting, setConnecting] = useState(false);
  const [selected, setSelected] = useState<Repository | null>(null);

  const builds = buildsQ.data ?? [];
  const buildName = (id?: number | null) => builds.find((b) => b.id === id)?.name ?? "—";

  const columns: Column<Repository>[] = [
    { id: "provider", header: "PROVIDER", width: "0.9fr", render: (r) => <Badge tone={providerTone(r.provider)}>{r.provider}</Badge> },
    {
      id: "repo",
      header: "REPOSITORY",
      width: "1.8fr",
      render: (r) => (
        <span style={{ color: "var(--text)" }}>
          {r.owner}/{r.name}
        </span>
      ),
    },
    { id: "branch", header: "BRANCH", width: "0.9fr", render: (r) => <span className={styles.cell}>{r.defaultBranch ?? "—"}</span> },
    {
      id: "build",
      header: "СБОРКА",
      width: "1.2fr",
      render: (r) => (
        <span className={styles.cell} style={r.buildId == null ? { color: "var(--med)" } : undefined}>
          {r.buildId == null ? "unbound" : buildName(r.buildId)}
        </span>
      ),
    },
    {
      id: "connected",
      header: "CONNECTED",
      width: "1.2fr",
      render: (r) => <span className={styles.cell}>{new Date(r.connectedAt).toLocaleString()}</span>,
    },
  ];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>repositories</h1>
          <div style={{ flex: 1 }} />
          <Button variant="primary" onClick={() => setConnecting(true)}>
            + connect repository
          </Button>
        </div>
        <p className={styles.blurb}>
          repositories the hub watches. Connecting installs a webhook; every provider action lands in the repo's
          Событие journal and feeds its agent Экземпляр.
        </p>

        <div className={styles.list}>
          <EntityList
            columns={columns}
            rows={reposQ.data ?? []}
            keyOf={(r) => String(r.id)}
            onRowClick={setSelected}
            empty={reposQ.loading ? "loading…" : "no repositories connected — link one from your identities"}
          />
        </div>
      </div>

      <RepoDrawer repo={selected} builds={builds} onClose={() => setSelected(null)} reload={reposQ.reload} />
      <ConnectDrawer open={connecting} builds={builds} onClose={() => setConnecting(false)} reload={reposQ.reload} />
    </div>
  );
}

function RepoDrawer({
  repo,
  builds,
  onClose,
  reload,
}: {
  repo: Repository | null;
  builds: AgentBuild[];
  onClose: () => void;
  reload: () => void;
}) {
  const api = useHubApi();
  const eventsQ = useRepoEvents(repo?.id ?? null);
  const [busy, setBusy] = useState(false);

  if (!repo) return null;

  const bind = async (buildId: number) => {
    setBusy(true);
    try {
      await api.setRepositoryBuild(repo.id, buildId);
      reload();
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    try {
      await api.disconnectRepository(repo.id);
      reload();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const events = eventsQ.data ?? [];

  return (
    <Drawer open title={`◆ ${repo.owner}/${repo.name}`} onClose={onClose} width={520}>
      <KeyValueList
        rows={[
          { key: "provider", value: repo.provider },
          { key: "default branch", value: repo.defaultBranch ?? "—" },
          { key: "external id", value: repo.externalId, tone: "dim" },
          { key: "connected", value: new Date(repo.connectedAt).toLocaleString() },
        ]}
      />

      <label className={styles.label}>СБОРКА</label>
      <select
        className={styles.select}
        value={repo.buildId ?? ""}
        disabled={busy}
        onChange={(e) => e.target.value && bind(Number(e.target.value))}
      >
        <option value="">— unbound —</option>
        {builds.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name}
            {b.isDefault ? " (default)" : ""}
          </option>
        ))}
      </select>

      <label className={styles.label}>СОБЫТИЯ — webhook journal</label>
      <div className={styles.journal}>
        {events.length === 0 && (
          <div className={styles.journalEmpty}>{eventsQ.loading ? "loading…" : "no events yet — push something"}</div>
        )}
        {events.map((e) => (
          <div key={e.id} className={styles.eventRow}>
            <span className={styles.eventAction}>{e.action}</span>
            <span className={styles.eventSha}>{e.commitSha?.slice(0, 8) ?? ""}</span>
            <span className={styles.eventRef}>{e.ref ?? ""}</span>
            <span className={styles.eventTime}>{new Date(e.receivedAt).toLocaleString()}</span>
          </div>
        ))}
      </div>

      <div className={styles.actions}>
        <Button variant="ghost" disabled={busy} onClick={disconnect}>
          disconnect
        </Button>
      </div>
      <p className={styles.hint}>Disconnecting removes the webhook from the provider.</p>
    </Drawer>
  );
}

function ConnectDrawer({
  open,
  builds,
  onClose,
  reload,
}: {
  open: boolean;
  builds: AgentBuild[];
  onClose: () => void;
  reload: () => void;
}) {
  const api = useHubApi();
  const meQ = useMe();
  const [identityId, setIdentityId] = useState<number | null>(null);
  const [externalId, setExternalId] = useState("");
  const [buildId, setBuildId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reposQ = useIdentityRepos(open ? identityId : null);

  const identities = meQ.data?.identities ?? [];
  const providerRepos = reposQ.data ?? [];

  const submit = async () => {
    if (identityId == null || !externalId) return;
    setBusy(true);
    setError(null);
    try {
      await api.connectRepository({
        identityId,
        externalId,
        buildId: buildId ? Number(buildId) : undefined,
      });
      reload();
      setExternalId("");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "connect failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open={open} title="◆ connect repository" onClose={onClose} width={460}>
      <label className={styles.label}>IDENTITY</label>
      <select
        className={styles.select}
        value={identityId ?? ""}
        onChange={(e) => {
          setIdentityId(e.target.value ? Number(e.target.value) : null);
          setExternalId("");
        }}
      >
        <option value="">— pick an identity —</option>
        {identities.map((i) => (
          <option key={i.id} value={i.id}>
            {i.provider} / {i.username}
          </option>
        ))}
      </select>

      <label className={styles.label}>REPOSITORY</label>
      <select
        className={styles.select}
        value={externalId}
        disabled={identityId == null || reposQ.loading}
        onChange={(e) => setExternalId(e.target.value)}
      >
        <option value="">{reposQ.loading ? "loading…" : "— pick a repository —"}</option>
        {providerRepos.map((r) => (
          <option key={r.externalId} value={r.externalId}>
            {r.owner}/{r.name}
            {r.private ? " 🔒" : ""}
          </option>
        ))}
      </select>

      <label className={styles.label}>
        СБОРКА <span className={styles.note}>— optional, default build applies</span>
      </label>
      <select className={styles.select} value={buildId} onChange={(e) => setBuildId(e.target.value)}>
        <option value="">— default —</option>
        {builds.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name}
          </option>
        ))}
      </select>

      {error && <p className={styles.error}>{error}</p>}
      <div className={styles.actions}>
        <Button variant="primary" disabled={busy || identityId == null || !externalId} onClick={submit}>
          ▶ connect
        </Button>
        <Button variant="ghost" onClick={onClose}>
          cancel
        </Button>
      </div>
      <p className={styles.hint}>The hub installs a webhook for all repo actions; events start flowing immediately.</p>
    </Drawer>
  );
}
