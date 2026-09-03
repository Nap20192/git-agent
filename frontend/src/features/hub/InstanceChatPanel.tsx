/** Chat with a repository's agent Экземпляр (mirrors runs/ChatPanel). The hub
 *  wakes a down instance and proxies into its checkpoint thread; the contract
 *  has no history endpoint, so the transcript is session-local. */
import { useEffect, useRef, useState } from "react";
import { useHubApi, type ChatEvent } from "@/api/hub";
import { Panel, PanelHeader } from "@/components/primitives";
import styles from "./chat.module.css";

interface Turn {
  role: "user" | "agent";
  text: string;
}

export function InstanceChatPanel({
  instanceId,
  agentLabel,
  onStatusChange,
}: {
  /** null → the repo has no agent yet; the panel explains instead of failing. */
  instanceId: number | null;
  /** Which watcher's agent this is (its Сборка name). */
  agentLabel?: string;
  onStatusChange?: () => void;
}) {
  const api = useHubApi();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState<{ text: string; activity: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns, live]);

  const send = async () => {
    const message = input.trim();
    if (!message || busy || instanceId == null) return;
    setInput("");
    setError(null);
    setBusy(true);
    setTurns((t) => [...t, { role: "user", text: message }]);
    setLive({ text: "", activity: "" });
    let reply = "";
    try {
      await api.chat(instanceId, message, (e: ChatEvent) => {
        if (e.kind === "token" && e.text) {
          reply += e.text;
          setLive((l) => ({ activity: "", ...l, text: reply }));
        }
        if (e.kind === "activity" && e.text) setLive((l) => ({ text: reply, ...l, activity: e.text! }));
      });
      setTurns((t) => [...t, { role: "agent", text: reply }]);
      onStatusChange?.(); // chat may have woken a down instance
    } catch (err) {
      setError(err instanceof Error ? err.message : "chat failed");
    } finally {
      setLive(null);
      setBusy(false);
    }
  };

  return (
    <Panel className={styles.panel}>
      <PanelHeader
        icon="✳"
        title="ASK THE AGENT"
        right={<span className={styles.hint}>{agentLabel ?? "it knows this repository"}</span>}
      />
      <div className={styles.transcript} ref={scrollRef}>
        {instanceId == null && (
          <div className={styles.empty}>This repository has no agent yet — bind a Сборка in settings to start one.</div>
        )}
        {instanceId != null && turns.length === 0 && !live && (
          <div className={styles.empty}>
            Ask about the code, a recent Событие, or a finding. If the agent is asleep, your message wakes it.
          </div>
        )}
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
          placeholder={instanceId == null ? "no agent yet" : busy ? "agent is working…" : "Ask about this repository…"}
          disabled={busy || instanceId == null}
          rows={2}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button type="button" className={styles.send} disabled={busy || !input.trim() || instanceId == null} onClick={send}>
          {busy ? "…" : "Send"}
        </button>
      </div>
    </Panel>
  );
}
