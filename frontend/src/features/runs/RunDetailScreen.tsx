/** Run detail: interactive graph + node inspector + event stream, for live and
 *  finished runs alike (the stream replays from cursor 0). */
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useApi, isActive, isResumable } from "@/api";
import type { GraphNode, RunLimits } from "@/api";
import { useGraph, useRun, useRunStream } from "@/hooks";
import { Button, Panel, PanelHeader, StatusBadge } from "@/components/primitives";
import { elapsed } from "@/lib/format.ts";
import { GraphCanvas } from "./GraphCanvas.tsx";
import { AgentList } from "./AgentList.tsx";
import { NodeInspector } from "./NodeInspector.tsx";
import { EventStream } from "./EventStream.tsx";
import { ChatPanel } from "./ChatPanel.tsx";
import styles from "./run.module.css";

export function RunDetailScreen() {
  const { id = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();
  const runQ = useRun(id);
  const graphQ = useGraph(id);
  const stream = useRunStream(id);
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<"graph" | "list">("graph");

  const run = runQ.data;
  const live = run ? isActive(run.status) : false;

  // Merge topology (graph) with live per-node status (stream). The graph is a
  // one-shot fetch, so the stream carries the truth: completed nodes come from
  // its node_status events; while live, a completed node's still-pending
  // successor is the one now running (pipeline emits no per-node "running").
  const nodes: GraphNode[] = useMemo(() => {
    const base = graphQ.data?.nodes ?? [];
    const merged = base.map((n) => ({ ...n, status: stream.nodeStatus[n.id] ?? n.status }));
    if (live) {
      const byId = new Map(merged.map((n) => [n.id, n]));
      for (const e of graphQ.data?.edges ?? []) {
        const from = byId.get(e.from);
        const to = byId.get(e.to);
        if (from?.status === "completed" && to?.status === "pending") to.status = "running";
      }
    }
    return merged;
  }, [graphQ.data, stream.nodeStatus, live]);

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
    // продолжение: опц. поднять токен-бюджет (Enter пустым — прежние лимиты)
    const cur = run?.limits?.tokenBudget ?? 0;
    const raw = window.prompt(
      "Продолжить ран. Новый токен-бюджет (пусто — прежние лимиты):",
      cur ? String(cur) : "",
    );
    let limits: RunLimits | undefined;
    if (raw !== null && raw.trim() !== "") {
      const n = Number(raw.trim());
      if (Number.isFinite(n) && n > 0) limits = { ...run?.limits, tokenBudget: n };
    }
    await api.resumeRun(id, limits);
    runQ.reload();
  };
  const remove = async () => {
    await api.deleteRun(id);
    navigate("/runs");
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
              ↻ continue
            </Button>
          )}
          {run.hasReport && (
            <Button variant="outline" onClick={() => navigate(`/runs/${id}/report`)}>
              → report
            </Button>
          )}
          {!live && (
            <Button variant="ghost" onClick={remove}>
              ✕ delete
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
            right={
              <span className={styles.viewToggle}>
                {(["graph", "list"] as const).map((v) => (
                  <span
                    key={v}
                    className={[styles.viewTab, view === v ? styles.viewTabOn : ""].join(" ")}
                    onClick={() => setView(v)}
                  >
                    {v}
                  </span>
                ))}
                <span className={styles.viewCount}>{nodes.length}</span>
              </span>
            }
          />
          <div style={{ flex: 1, minHeight: 0 }}>
            {view === "graph" ? (
              <GraphCanvas nodes={nodes} edges={graphQ.data?.edges ?? []} selectedId={selected} onSelect={setSelected} eventCounts={eventCounts} />
            ) : (
              <AgentList nodes={nodes} selectedId={selected} onSelect={setSelected} eventCounts={eventCounts} />
            )}
          </div>
        </Panel>
        <NodeInspector runId={id} node={selectedNode} events={selected ? stream.eventsByNode[selected] ?? [] : []} onClose={() => setSelected(null)} />
      </div>

      {/* event stream + post-run chat (agent runs, once finished) share the row */}
      <div className={styles.bottom}>
        <EventStream logs={stream.logs} nodes={nodes} selectedNodeId={selected} live={live} />
        {!live && nodes.some((n) => n.id === "lead") && (
          <div className={styles.chatCol}>
            <ChatPanel runId={id} />
          </div>
        )}
      </div>
    </div>
  );
}
