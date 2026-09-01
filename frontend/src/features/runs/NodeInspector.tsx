/**
 * Right-panel inspector for the selected graph node. Tabs:
 *   overview | system prompt | tools | delegation? | events
 * Procedural nodes (scan/report): prompt tab shows "no LLM prompt (procedural
 * node)", tools tab lists the real sandbox commands. Lead/sub-agent nodes show
 * the build_agent system prompt + the sandbox toolset (+ `task` for the lead).
 * Sub-agent nodes add a "delegation" tab: the real task_tool inputs + result
 * metadata (status, stop_reason, token usage, tool receipts, receipt verdict).
 */
import { useState } from "react";
import type { GraphNode, RunEvent, TokenUsage } from "@/api";
import { useNodeSpec } from "@/hooks";
import { Badge, CodeBlock, KeyValueList, Panel, PanelHeader, Tabs } from "@/components/primitives";
import type { KeyValueRow } from "@/components/primitives";
import { nodeTone } from "@/lib/status.ts";
import styles from "./NodeInspector.module.css";

export interface NodeInspectorProps {
  runId: string;
  node: GraphNode | null;
  events: RunEvent[];
  onClose: () => void;
}

type TabId = "overview" | "prompt" | "tools" | "delegation" | "events";

function usageLabel(u: TokenUsage): string {
  return `${u.totalTokens.toLocaleString()} tok · ${u.inputTokens.toLocaleString()} in / ${u.outputTokens.toLocaleString()} out`;
}

export function NodeInspector({ runId, node, events, onClose }: NodeInspectorProps) {
  const [tab, setTab] = useState<TabId>("overview");
  const { data: spec } = useNodeSpec(runId, node?.id ?? null);

  if (!node) {
    return (
      <Panel style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span style={{ color: "var(--dim)", fontSize: 12 }}>← select a node to inspect</span>
      </Panel>
    );
  }

  const delegation = spec?.delegation ?? null;
  const tabs = [
    { id: "overview", label: "overview" },
    { id: "prompt", label: "system prompt" },
    { id: "tools", label: "tools", badge: spec?.tools.length },
    ...(delegation ? [{ id: "delegation", label: "delegation" }] : []),
    { id: "events", label: "events", badge: events.length },
  ];

  const overviewRows: KeyValueRow[] = [
    { key: "id", value: node.id },
    { key: "kind", value: spec?.subagentType ? `sub-agent (${spec.subagentType})` : node.kind },
    { key: "status", value: node.status, tone: nodeTone(node.status) },
    { key: "model", value: spec?.model ?? "—" },
    { key: "memory preset", value: spec?.memoryPreset ?? "—" },
  ];
  if (spec?.maxTurns) overviewRows.push({ key: "max turns", value: String(spec.maxTurns) });
  if (spec?.timeoutSeconds) overviewRows.push({ key: "timeout", value: `${spec.timeoutSeconds}s` });
  if (delegation?.tokenUsage) overviewRows.push({ key: "token usage", value: usageLabel(delegation.tokenUsage), tone: "amber" });
  if (delegation?.stopReason) overviewRows.push({ key: "stop reason", value: delegation.stopReason, tone: "high" });
  overviewRows.push({ key: "events", value: String(events.length) });
  overviewRows.push({ key: "description", value: <span style={{ textAlign: "left" }}>{spec?.description ?? "…"}</span> });

  return (
    <Panel style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0 }}>
      <PanelHeader
        icon={node.kind === "agent" ? "◆" : "▣"}
        iconTone={node.kind === "agent" ? "blue" : "amber"}
        title={node.label}
        right={
          <>
            <Badge tone={nodeTone(node.status)} outline>
              {node.status}
            </Badge>
            <span className={styles.close} onClick={onClose}>
              ✕
            </span>
          </>
        }
      />
      <div className={styles.tabsWrap}>
        <Tabs items={tabs} value={tab} onChange={(id) => setTab(id as TabId)} />
      </div>
      <div className={styles.body}>
        {tab === "overview" && <KeyValueList rows={overviewRows} />}

        {tab === "prompt" &&
          (spec?.systemPrompt ? (
            <CodeBlock label={node.kind === "agent" ? "build_agent(system_prompt=…)" : "inline prompt"}>{spec.systemPrompt}</CodeBlock>
          ) : (
            <div className={styles.note}>no LLM prompt — procedural node (pure code)</div>
          ))}

        {tab === "tools" && (
          <div className={styles.rows}>
            {(spec?.tools ?? []).map((t) => (
              <div key={t.name} className={styles.tool}>
                <div className={styles.toolHead}>
                  <span style={{ color: t.name === "task" ? "var(--blue)" : "var(--amber)" }}>{t.name === "task" ? "◆" : "⚒"}</span>
                  <span className={styles.toolName}>{t.name}</span>
                </div>
                <div className={styles.toolDesc}>{t.description}</div>
                {t.signature && <code className={styles.sig}>{t.signature}</code>}
              </div>
            ))}
            {(spec?.tools ?? []).length === 0 && <div className={styles.note}>no tools declared</div>}
          </div>
        )}

        {tab === "delegation" && delegation && (
          <div className={styles.rows}>
            <KeyValueList
              rows={[
                { key: "task id", value: delegation.taskId },
                { key: "sub-agent type", value: delegation.subagentType },
                { key: "status", value: delegation.status, tone: delegation.status === "completed" ? "low" : "crit" },
                ...(delegation.stopReason ? [{ key: "stop reason", value: delegation.stopReason, tone: "high" as const }] : []),
                ...(delegation.tokenUsage ? [{ key: "token usage", value: usageLabel(delegation.tokenUsage), tone: "amber" as const }] : []),
                ...(delegation.receiptVerdict ? [{ key: "receipts", value: `${delegation.receiptVerdict.cited} cited / ${delegation.receiptVerdict.uncited} uncited`, tone: delegation.receiptVerdict.ok ? ("low" as const) : ("high" as const) }] : []),
              ]}
            />
            <div className={styles.section}>acceptance criteria</div>
            <ul className={styles.criteria}>
              {delegation.acceptanceCriteria.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
            <div className={styles.section}>prompt</div>
            <CodeBlock copyable={false}>{delegation.prompt}</CodeBlock>
            {delegation.resultBrief && (
              <>
                <div className={styles.section}>result brief</div>
                <CodeBlock copyable={false}>{delegation.resultBrief}</CodeBlock>
              </>
            )}
            <div className={styles.section}>tool receipts</div>
            <div className={styles.rows}>
              {delegation.toolReceipts.map((r) => (
                <div key={r.id} className={styles.receipt}>
                  <span className={styles.receiptId}>{r.id}</span>
                  <span className={styles.receiptTool}>{r.tool}</span>
                  <span className={styles.receiptSummary}>{r.summary}</span>
                </div>
              ))}
              {delegation.toolReceipts.length === 0 && <div className={styles.note}>no receipts</div>}
            </div>
          </div>
        )}

        {tab === "events" && (
          <div className={styles.rows}>
            {events.length === 0 && <div className={styles.note}>no events for this node yet</div>}
            {events.map((e) => (
              <NodeEventRow key={e.cursor} event={e} />
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

function NodeEventRow({ event }: { event: RunEvent }) {
  const [open, setOpen] = useState(false);
  const { summary, body } = eventDetail(event);
  const expandable = !!body;
  return (
    <div className={styles.event}>
      <div className={styles.eventHead} onClick={() => expandable && setOpen((o) => !o)} style={{ cursor: expandable ? "pointer" : "default" }}>
        <span className={styles.eventType}>{event.type}</span>
        <span className={styles.eventMsg}>{summary}</span>
        {expandable && <span className={styles.eventChevron}>{open ? "▾" : "▸"}</span>}
      </div>
      {open && body && <CodeBlock copyable={false}>{body}</CodeBlock>}
    </div>
  );
}

/** Inline summary + full expandable body for a node event — reasoning, tool
 *  calls with args, tool results, lifecycle. */
function eventDetail(event: RunEvent): { summary: string; body: string | null } {
  const d = event.data;
  if (d?.kind === "task_step") {
    const calls = (d.toolCalls ?? []).map((c) => `⚙ ${c.name}(${c.args})`).join("\n");
    if (d.frameKind === "tool") {
      const head = d.toolName ? `↩ ${d.toolName}` : "↩ tool result";
      return { summary: head, body: [d.text, calls].filter(Boolean).join("\n\n") || null };
    }
    const summary = d.text?.trim()?.split("\n")[0] || (calls ? "tool call" : "thinking…");
    return { summary, body: [d.text, calls].filter(Boolean).join("\n\n") || null };
  }
  if (d?.kind === "task_terminal") {
    const err = d.error ? `\n${d.error}` : "";
    return { summary: d.status, body: `${d.usage ? usageLabel(d.usage) : d.status}${err}` };
  }
  if (d?.kind === "task_started") return { summary: `▶ ${d.subagentType} — ${d.description}`, body: null };
  if (event.message?.trim()) return { summary: event.message, body: null };
  return { summary: event.type, body: d ? JSON.stringify(d, null, 2) : null };
}
