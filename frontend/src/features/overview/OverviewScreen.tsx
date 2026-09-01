/** Overview — real aggregates derived from the runs list (no fantasy metrics). */
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import type { Run, RunStatus } from "@/api";
import { useRuns } from "@/hooks";
import { Panel, PanelHeader, StatusBadge } from "@/components/primitives";
import { runLabel, runTone, RUN_STATUS_ORDER } from "@/lib/status.ts";
import { toneVar, type Tone } from "@/lib/tone.ts";
import { elapsed, tokensLabel } from "@/lib/format.ts";
import styles from "./OverviewScreen.module.css";

interface Tile {
  label: string;
  value: number | string;
  sub: string;
  tone: Tone;
}

export function OverviewScreen() {
  const navigate = useNavigate();
  const runsQ = useRuns();
  const runs = runsQ.data ?? [];

  const counts = useMemo(() => {
    const c = {} as Record<RunStatus, number>;
    RUN_STATUS_ORDER.forEach((s) => (c[s] = 0));
    runs.forEach((r) => (c[r.status] += 1));
    return c;
  }, [runs]);

  const total = runs.length;
  const totalTokens = useMemo(
    () => runs.reduce((a, r) => a + (r.metrics.tokenUsage?.totalTokens ?? 0), 0),
    [runs],
  );
  const tiles: Tile[] = [
    { label: "total runs", value: total, sub: "all submitted", tone: "text" },
    { label: "running", value: counts.running + counts.pending, sub: "active now", tone: "amber" },
    { label: "succeeded", value: counts.succeeded, sub: "reports ready", tone: "low" },
    { label: "failed", value: counts.failed + counts.interrupted, sub: "failed + interrupted", tone: "crit" },
    { label: "tokens", value: totalTokens > 0 ? tokensLabel(totalTokens) : "—", sub: "sub-agent usage", tone: "blue" },
  ];

  const recent = runs.slice(0, 8);

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>overview</h1>
          <span className={styles.path}>~/git-agent</span>
        </div>

        {runsQ.loading ? (
          <Panel className={styles.state}>loading…</Panel>
        ) : total === 0 ? (
          <Panel className={styles.state}>no runs yet</Panel>
        ) : (
          <>
            <div className={styles.tiles}>
              {tiles.map((t) => (
                <Panel key={t.label} className={styles.tile}>
                  <span className={styles.tileNum} style={{ color: toneVar(t.tone) }}>
                    {t.value}
                  </span>
                  <span className={styles.tileLabel}>{t.label}</span>
                  <span className={styles.tileSub}>{t.sub}</span>
                </Panel>
              ))}
            </div>

            <Panel className={styles.block}>
              <PanelHeader icon="◈" title="status distribution" right={`${total} total`} />
              <div className={styles.bar}>
                {RUN_STATUS_ORDER.filter((s) => counts[s] > 0).map((s) => (
                  <div
                    key={s}
                    className={styles.seg}
                    style={{ width: `${(counts[s] / total) * 100}%`, background: toneVar(runTone(s)) }}
                    title={`${runLabel(s)} ${counts[s]}`}
                  />
                ))}
              </div>
              <div className={styles.legend}>
                {RUN_STATUS_ORDER.map((s) => (
                  <div key={s} className={styles.legendRow}>
                    <span className={styles.swatch} style={{ background: toneVar(runTone(s)) }} />
                    <span className={styles.legendLabel}>{runLabel(s)}</span>
                    <span className={styles.legendCount}>{counts[s]}</span>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel className={styles.block}>
              <PanelHeader icon="$_" title="recent runs" right={`${recent.length} shown`} />
              <div className={styles.rows}>
                {recent.map((r) => (
                  <RecentRow key={r.id} run={r} onClick={() => navigate(`/runs/${r.id}`)} />
                ))}
              </div>
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}

function RecentRow({ run, onClick }: { run: Run; onClick: () => void }) {
  return (
    <div className={styles.row} onClick={onClick}>
      <span className={styles.rowStatus}>
        <StatusBadge status={run.status} />
      </span>
      <span className={styles.rowRepo}>{run.repo}</span>
      <span className={styles.rowModel}>{run.connection.model}</span>
      <span className={styles.rowElapsed}>{elapsed(run.metrics.elapsedSec)}</span>
      <span className={styles.rowGo}>→</span>
    </div>
  );
}
