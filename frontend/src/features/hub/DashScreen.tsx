/** /dash — сводка по Экземплярам на существующих ручках (тикет 012, п.2):
 *  running/down, События за 24ч по репозиториям, последние Находки по
 *  severity. Обновляется 15s-поллингом — это обзор, не live-вью. */
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useHubApi, type Finding, type RepoEvent } from "@/api/hub";
import { useAsync } from "@/hooks/useAsync.ts";
import { useBuilds, useHubRepositories, useInstances, useRunners } from "@/hooks";
import { Badge, Panel, PanelHeader, StatusDot } from "@/components/primitives";
import { FindingRow } from "./RepoScreen.tsx";
import styles from "./hub.module.css";

const POLL_MS = 15000;
const DAY_MS = 24 * 60 * 60 * 1000;
const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;

function severityTone(s: string): "crit" | "high" | "med" | "low" | "info" {
  switch (s) {
    case "critical":
      return "crit";
    case "high":
      return "high";
    case "medium":
      return "med";
    case "low":
      return "low";
    default:
      return "info";
  }
}

export function DashScreen() {
  const api = useHubApi();
  const navigate = useNavigate();
  const instancesQ = useInstances();
  const reposQ = useHubRepositories();
  const buildsQ = useBuilds();
  const runnersQ = useRunners();

  const repos = reposQ.data ?? [];
  const instances = instancesQ.data ?? [];

  // фан-аут по существующим ручкам: события каждого репо, находки каждого Экземпляра
  const eventsQ = useAsync<Map<number, RepoEvent[]>>(
    async () => {
      const entries = await Promise.all(
        repos.map(async (r) => [r.id, await api.listRepositoryEvents(r.id)] as const),
      );
      return new Map(entries);
    },
    [repos.map((r) => r.id).join(",")],
  );
  const findingsQ = useAsync<Finding[]>(
    async () => {
      const lists = await Promise.all(instances.map((i) => api.listInstanceFindings(i.id)));
      return lists.flat().sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? ""));
    },
    [instances.map((i) => i.id).join(",")],
  );

  const reloadRef = useRef(() => {});
  reloadRef.current = () => {
    instancesQ.reload();
    reposQ.reload();
    runnersQ.reload();
    eventsQ.reload();
    findingsQ.reload();
  };
  useEffect(() => {
    const t = setInterval(() => reloadRef.current(), POLL_MS);
    return () => clearInterval(t);
  }, []);

  const running = instances.filter((i) => i.status === "running").length;
  const now = Date.now();
  const allEvents = [...(eventsQ.data?.values() ?? [])].flat();
  const events24 = allEvents.filter((e) => now - new Date(e.receivedAt).getTime() < DAY_MS);
  const findings = findingsQ.data ?? [];
  const sevCounts = new Map(SEVERITIES.map((s) => [s as string, 0]));
  for (const f of findings) sevCounts.set(f.severity, (sevCounts.get(f.severity) ?? 0) + 1);

  const buildName = (id: number) => (buildsQ.data ?? []).find((b) => b.id === id)?.name;
  const repoName = (id: number) => {
    const r = repos.find((x) => x.id === id);
    return r ? `${r.owner}/${r.name}` : `repo #${id}`;
  };

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>
            <span className={styles.cardOwner}>hub/</span>dash
          </h1>
        </div>
        <p className={styles.blurb}>Сводка по всем Экземплярам: кто жив, что прилетело за сутки, что найдено.</p>

        <div className={styles.statusStrip}>
          <div className={styles.statusItem}>
            <span className={styles.statusLabel}>Экземпляры</span>
            <span className={styles.statusValue}>
              {running} running / {instances.length - running} down
            </span>
          </div>
          <div className={styles.statusItem}>
            <span className={styles.statusLabel}>События 24ч</span>
            <span className={styles.statusValue}>{eventsQ.data ? events24.length : "…"}</span>
          </div>
          <div className={styles.statusItem}>
            <span className={styles.statusLabel}>Находки</span>
            <span className={styles.statusValue}>
              {SEVERITIES.filter((s) => (sevCounts.get(s) ?? 0) > 0).map((s) => (
                <Badge key={s} tone={severityTone(s)}>
                  {s.slice(0, 4)} {sevCounts.get(s)}
                </Badge>
              ))}
              {findings.length === 0 && (findingsQ.loading ? "…" : "0")}
            </span>
          </div>
          <div className={styles.statusItem}>
            <span className={styles.statusLabel}>раннеры</span>
            <span className={styles.statusValue}>{(runnersQ.data ?? []).length}</span>
          </div>
        </div>

        <div className={styles.repoGrid}>
          <div className={styles.rail}>
            <Panel>
              <PanelHeader
                icon="▣"
                title="ЭКЗЕМПЛЯРЫ"
                right={<span className={styles.cell}>{instances.length}</span>}
              />
              {instances.length === 0 && (
                <div className={styles.panelEmpty}>
                  {instancesQ.loading && instancesQ.data === undefined
                    ? "loading…"
                    : "Нет Экземпляров — подключи репозиторий и Сборку."}
                </div>
              )}
              {instances.map((i) => {
                const repoEvents = eventsQ.data?.get(i.repositoryId) ?? [];
                const fresh = repoEvents.filter((e) => now - new Date(e.receivedAt).getTime() < DAY_MS);
                return (
                  <div key={i.id} className={`${styles.tlRow} ${styles.tlClickable}`} onClick={() => navigate(`/instances/${i.id}`)}>
                    <StatusDot tone={i.status === "running" ? "low" : "dim"} pulse={i.status === "running"} />
                    <div className={styles.tlBody}>
                      <div className={styles.tlHead}>
                        <span className={styles.tlAction}>{buildName(i.buildId) ?? `Экземпляр #${i.id}`}</span>
                        <span className={styles.tlMeta}>{repoName(i.repositoryId)}</span>
                        <span className={styles.tlTime}>{i.status}</span>
                      </div>
                      <div className={styles.tlReport}>
                        События 24ч: {eventsQ.data ? fresh.length : "…"} · sandbox: {i.sandboxStatus ?? "none"}
                        {i.updatedAt ? ` · upd ${new Date(i.updatedAt).toLocaleTimeString()}` : ""}
                      </div>
                    </div>
                  </div>
                );
              })}
            </Panel>
          </div>

          <div className={styles.rail}>
            <Panel>
              <PanelHeader
                icon="⚠"
                title="ПОСЛЕДНИЕ НАХОДКИ"
                right={<span className={styles.cell}>{findings.length}</span>}
              />
              {findings.length === 0 && (
                <div className={styles.panelEmpty}>
                  {findingsQ.loading && findingsQ.data === undefined ? "loading…" : "Пока чисто."}
                </div>
              )}
              {findings.slice(0, 12).map((f) => (
                <FindingRow key={f.id} finding={f} />
              ))}
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}
