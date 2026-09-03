/** Repositories — the hub's home. One card per connected repo showing its
 *  agent's presence (Экземпляр status), bound Сборка, and the latest Событие.
 *  Card → repo page; dashed card → connect flow (identity → provider repo →
 *  POST /api/repositories, hub installs the webhook). */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useHubApi, type AgentBuild, type AgentInstance, type Repository } from "@/api/hub";
import { useBuilds, useHubRepositories, useIdentityRepos, useInstances, useMe } from "@/hooks";
import { Badge, Button, Drawer } from "@/components/primitives";
import styles from "./hub.module.css";

export function AgentPresence({ instance, withLabel = true }: { instance?: AgentInstance; withLabel?: boolean }) {
  const status = instance == null ? "no agent yet" : instance.status === "running" ? "awake" : "asleep";
  const dotClass =
    instance == null ? styles.noAgent : instance.status === "running" ? styles.awake : styles.asleep;
  return (
    <span className={styles.presence}>
      <span className={`${styles.presenceDot} ${dotClass}`} />
      {withLabel && status}
    </span>
  );
}

export function RepositoriesScreen() {
  const navigate = useNavigate();
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const instancesQ = useInstances();
  const [connecting, setConnecting] = useState(false);

  const builds = buildsQ.data ?? [];
  // Card presence: the repo's awake agent wins; otherwise any of its agents.
  const instanceOf = (repoId: number) => {
    const mine = (instancesQ.data ?? []).filter((i) => i.repositoryId === repoId);
    return mine.find((i) => i.status === "running") ?? mine[0];
  };

  const repos = reposQ.data ?? [];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>Repositories</h1>
          <div style={{ flex: 1 }} />
          <Button variant="primary" onClick={() => setConnecting(true)}>
            Connect repository
          </Button>
        </div>
        <p className={styles.blurb}>
          Each connected repository gets its own agent. Pushes and pull requests land in its journal (События), and
          the agent turns them into reports. Open a repository to read what it found — or ask it directly.
        </p>

        <div className={styles.cards}>
          {repos.map((r) => (
            <RepoCard key={r.id} repo={r} instance={instanceOf(r.id)} onOpen={() => navigate(`/repos/${r.id}`)} />
          ))}
          <div className={`${styles.card} ${styles.addCard}`} onClick={() => setConnecting(true)}>
            <span>＋ Connect a repository</span>
          </div>
        </div>
        {reposQ.loading && repos.length === 0 && <p className={styles.hint}>loading…</p>}
      </div>

      <ConnectDrawer open={connecting} builds={builds} onClose={() => setConnecting(false)} reload={reposQ.reload} />
    </div>
  );
}

function RepoCard({
  repo,
  instance,
  onOpen,
}: {
  repo: Repository;
  instance?: AgentInstance;
  onOpen: () => void;
}) {
  return (
    <div className={styles.card} onClick={onOpen}>
      <div className={styles.cardTop}>
        <Badge tone={repo.provider === "github" ? "text" : "burnt"}>{repo.provider}</Badge>
        <div style={{ flex: 1 }} />
        <AgentPresence instance={instance} />
      </div>
      <div className={styles.cardName}>
        <span className={styles.cardOwner}>{repo.owner}/</span>
        {repo.name}
      </div>
      <div className={styles.cardMeta}>
        {repo.defaultBranch && <span className={styles.mono}>{repo.defaultBranch}</span>}
        <span>connected {new Date(repo.connectedAt).toLocaleDateString()}</span>
      </div>
    </div>
  );
}

export function ConnectDrawer({
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
    <Drawer open={open} title="Connect repository" onClose={onClose} width={460}>
      <label className={styles.label}>Identity</label>
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

      <label className={styles.label}>Repository</label>
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
        Сборка <span className={styles.note}>— optional, the default build applies</span>
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
          Connect
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
      <p className={styles.hint}>
        Connecting installs a webhook on the repository. Its agent starts receiving События immediately.
      </p>
    </Drawer>
  );
}
