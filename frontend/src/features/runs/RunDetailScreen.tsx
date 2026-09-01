/** Run detail: interactive graph + node inspector + event stream, for live and
 *  finished runs alike (the stream replays from cursor 0). */
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useApi, isActive, isResumable } from "@/api";
import type { GraphNode } from "@/api";
import { useGraph, useRun, useRunStream } from "@/hooks";
import { Button, Panel, PanelHeader, StatusBadge } from "@/components/primitives";
import { elapsed } from "@/lib/format.ts";
import { GraphCanvas } from "./GraphCanvas.tsx";
import { NodeInspector } from "./NodeInspector.tsx";
import { EventStream } from "./EventStream.tsx";
import styles from "./run.module.css";

export function RunDetailScreen() {
  const { id = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();
  const runQ = useRun(id);
  const graphQ = useGraph(id);
  const stream = useRunStream(id);
  const [selected, setSelected] = useState<string | null>(null);

  const run = runQ.data;
  const live = run ? isActive(run.status) : false;

  // Merge topology (graph) with live per-node status (stream).
  const nodes: GraphNode[] = useMemo(() => {
    const base = graphQ.data?.nodes ?? [];
    return base.map((n) => ({ ...n, status: stream.nodeStatus[n.id] ?? n.status }));
  }, [graphQ.data, stream.nodeStatus]);

  const eventCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const [k, v] of Object.entries(stream.eventsByNode)) c[k] = v.length;
    return c;
  }, [stream.eventsByNode]);

  const selectedNode = nodes.find((n) => n.id === selected) ?? null;

  const cancel = async () => {
    await api.cancelRun(id);
    runQ.reload();
  };
  const resume = async () => {
    await api.resumeRun(id);
    runQ.reload();
  };

  if (!run) return <div className={styles.loading}>loading run…</div>;

  return (
    <div className={styles.detail}>
      {/* header */}
      <div className={styles.header}>
        <div className={styles.headerMain}>
          <span className={styles.repo}>{run.repo}</span>
          <span className={styles.sub}>{run.commitSha?.slice(0, 7) ?? "—"}</span>
          <span className={styles.sub}>{run.connection.model}</span>
          <span className={styles.sub}>sandbox {run.sandbox ?? "—"}</span>
          <StatusBadge status={run.status} />
          {run.attempt > 1 && <span className={styles.attempt}>attempt {run.attempt}</span>}
          {run.stopReason && <span className={styles.stop}>{run.stopReason}</span>}
        </div>
        <div className={styles.headerActions}>
          {run.metrics.tokenUsage && (
            <span className={styles.sub}>{run.metrics.tokenUsage.totalTokens.toLocaleString()} tok</span>
          )}
          <span className={styles.timing}>{elapsed(run.metrics.elapsedSec)}</span>
          {live && (
            <Button variant="ghost" onClick={cancel}>
              ■ cancel
            </Button>
          )}
          {isResumable(run.status) && (
            <Button variant="ghost" onClick={resume}>
              ↻ resume
            </Button>
          )}
          {run.hasReport && (
            <Button variant="outline" onClick={() => navigate(`/runs/${id}/report`)}>
              → report
            </Button>
          )}
        </div>
      </div>

      {/* graph + inspector */}
      <div className={styles.mid}>
        <Panel style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
          <PanelHeader
            icon="╱╱"
            title="AGENT ORCHESTRATION"
            right={<span>{nodes.length} nodes</span>}
          />
          <div style={{ flex: 1, minHeight: 0 }}>
            <GraphCanvas nodes={nodes} edges={graphQ.data?.edges ?? []} selectedId={selected} onSelect={setSelected} eventCounts={eventCounts} />
          </div>
        </Panel>
        <NodeInspector runId={id} node={selectedNode} events={selected ? stream.eventsByNode[selected] ?? [] : []} onClose={() => setSelected(null)} />
      </div>

      {/* event stream */}
      <div className={styles.bottom}>
        <EventStream logs={stream.logs} nodes={nodes} selectedNodeId={selected} live={live} />
      </div>
    </div>
  );
}
