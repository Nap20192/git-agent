/** Post-run chat with the lead agent. Continues the run's checkpoint thread —
 *  the agent answers with full run context and can investigate further. Only for
 *  finished agent runs. Streams the reply; reloads authoritative history on done. */
import { useEffect, useRef, useState } from "react";
import { useApi } from "@/api";
import type { ChatTurn, RunEvent } from "@/api";
import { Panel, PanelHeader } from "@/components/primitives";
import styles from "./chat.module.css";

interface Live {
  text: string;
  activity: string;
}

export function ChatPanel({ runId }: { runId: string }) {
  const api = useApi();
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState<Live | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.chatHistory(runId).then(setTurns).catch(() => {});
  }, [api, runId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns, live]);

  const send = async () => {
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setError(null);
    setBusy(true);
    setTurns((t) => [...t, { role: "user", text: message }]);
    setLive({ text: "", activity: "" });
    try {
      await api.sendChat(runId, message, (e: RunEvent) => {
        const d = e.data as Record<string, unknown> | undefined;
        if (d?.kind === "agent_step" && d?.text) setLive((l) => ({ ...(l ?? { text: "", activity: "" }), text: String(d.text) }));
        const calls = (d?.toolCalls as { name?: string }[] | undefined) ?? [];
        if (calls.length) setLive((l) => ({ ...(l ?? { text: "", activity: "" }), activity: `→ ${calls.map((c) => c.name).join(", ")}` }));
        if (e.type === "task_started") setLive((l) => ({ ...(l ?? { text: "", activity: "" }), activity: `▶ delegating: ${(d?.description as string) ?? ""}` }));
      });
      const hist = await api.chatHistory(runId);
      setTurns(hist);
    } catch (err) {
      setError(err instanceof Error ? err.message : "chat failed");
    } finally {
      setLive(null);
      setBusy(false);
    }
  };

  return (
    <Panel className={styles.panel}>
      <PanelHeader icon="✦" title="CHAT" right={<span className={styles.hint}>ask the agent about this run</span>} />
      <div className={styles.transcript} ref={scrollRef}>
        {turns.length === 0 && !live && <div className={styles.empty}>No messages yet. Ask a follow-up about the findings, the code, or request a deeper look.</div>}
        {turns.map((t, i) => (
          <div key={i} className={t.role === "user" ? styles.user : styles.agent}>
            <span className={styles.role}>{t.role === "user" ? "you" : "agent"}</span>
            <div className={styles.bubble}>{t.text || (t.role === "agent" ? "…" : "")}</div>
          </div>
        ))}
        {live && (
          <div className={styles.agent}>
            <span className={styles.role}>agent</span>
            <div className={styles.bubble}>
              {live.text || <span className={styles.thinking}>thinking…</span>}
              {live.activity && <div className={styles.activity}>{live.activity}</div>}
            </div>
          </div>
        )}
      </div>
      {error && <div className={styles.error}>{error}</div>}
      <div className={styles.composer}>
        <textarea
          className={styles.input}
          value={input}
          placeholder={busy ? "agent is working…" : "ask a follow-up…"}
          disabled={busy}
          rows={2}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button type="button" className={styles.send} disabled={busy || !input.trim()} onClick={send}>
          {busy ? "…" : "send"}
        </button>
      </div>
    </Panel>
  );
}
