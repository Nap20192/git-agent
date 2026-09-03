/** Экземпляры Агентов — long-lived per-repository agents. down = checkpoint
 *  in DB, running = live in a runner slot. */
import { useNavigate } from "react-router-dom";
import type { AgentInstance } from "@/api/hub";
import { useBuilds, useHubRepositories, useInstances } from "@/hooks";
import { EntityList, StatusDot } from "@/components/primitives";
import type { Column } from "@/components/primitives";
import styles from "./hub.module.css";

export function instanceTone(status: AgentInstance["status"]) {
  return status === "running" ? ("low" as const) : ("dim" as const);
}

export function InstancesScreen() {
  const navigate = useNavigate();
  const instancesQ = useInstances();
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();

  const repoName = (id: number) => {
    const r = (reposQ.data ?? []).find((x) => x.id === id);
    return r ? `${r.owner}/${r.name}` : `#${id}`;
  };
  const buildName = (id: number) => (buildsQ.data ?? []).find((b) => b.id === id)?.name ?? `#${id}`;

  const columns: Column<AgentInstance>[] = [
    {
      id: "status",
      header: "STATUS",
      width: "0.9fr",
      render: (i) => (
        <span className={styles.dotCell}>
          <StatusDot tone={instanceTone(i.status)} pulse={i.status === "running"} />
          <span style={{ fontSize: 11, color: "var(--muted)" }}>{i.status}</span>
        </span>
      ),
    },
    { id: "repo", header: "REPOSITORY", width: "1.6fr", render: (i) => <span style={{ color: "var(--text)" }}>{repoName(i.repositoryId)}</span> },
    { id: "build", header: "СБОРКА", width: "1.1fr", render: (i) => <span className={styles.cell}>{buildName(i.buildId)}</span> },
    { id: "runner", header: "RUNNER", width: "0.8fr", render: (i) => <span className={styles.cell}>{i.runnerId != null ? `#${i.runnerId}` : "—"}</span> },
    {
      id: "updated",
      header: "UPDATED",
      width: "1.2fr",
      render: (i) => <span className={styles.cell}>{i.updatedAt ? new Date(i.updatedAt).toLocaleString() : "—"}</span>,
    },
  ];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>instances</h1>
        </div>
        <p className={styles.blurb}>
          the long-lived agent of each repository: one per (Сборка, Репозиторий), one checkpoint thread accumulating
          knowledge. События and your chat both land in its thread; idle instances go down and wake on demand.
        </p>

        <div className={styles.list}>
          <EntityList
            columns={columns}
            rows={instancesQ.data ?? []}
            keyOf={(i) => String(i.id)}
            onRowClick={(i) => navigate(`/instances/${i.id}`)}
            empty={instancesQ.loading ? "loading…" : "no instances yet — connect a repository and bind a build"}
          />
        </div>
      </div>
    </div>
  );
}
