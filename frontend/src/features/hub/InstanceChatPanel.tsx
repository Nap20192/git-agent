/** Chat with an agent Экземпляр: «❯ you» / agent (streaming cursor) /
 *  «→ activity» rows over the hub chat SSE. The hub wakes a down instance;
 *  there is no history endpoint, so the transcript is session-local.
 *  Renders log + prompt only — the host wraps it (panel or tab box). */
import { useEffect, useRef, useState } from "react";
import { useHubApi, type ChatEvent } from "@/api/hub";
import { Rich } from "./rich.tsx";
import { errMsg } from "./ui.tsx";

interface Row {
  role: "user" | "agent" | "activity";
  text: string;
  streaming?: boolean;
}

export function InstanceChatPanel({
  instanceId,
  empty,
  onStatusChange,
  onActivity,
}: {
  /** null → the repo has no agent yet; the panel explains instead of failing. */
  instanceId: number | null;
  empty: string;
  onStatusChange?: () => void;
  /** Fires per activity SSE frame — lets a host screen keep an activity log. */
  onActivity?: (text: string) => void;
}) {
  const api = useHubApi();
  const [rows, setRows] = useState<Row[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [rows]);

  const send = async () => {
    const message = input.trim();
    if (!message || busy || instanceId == null) return;
    setInput("");
    setBusy(true);
    setRows((r) => [...r, { role: "user", text: message }, { role: "agent", text: "", streaming: true }]);
    const patchLast = (fn: (m: Row) => Row) =>
      setRows((r) => {
        const i = r.length - 1;
        return i < 0 ? r : [...r.slice(0, i), fn(r[i])];
      });
    try {
      await api.chat(instanceId, message, (e: ChatEvent) => {
        if (e.kind === "token" && e.text) patchLast((m) => ({ ...m, text: m.text + e.text }));
        if (e.kind === "activity" && e.text) {
          // keep the streaming agent row last: activity lands above it
          setRows((r) => {
            const last = r[r.length - 1];
            return last?.streaming ? [...r.slice(0, -1), { role: "activity", text: e.text! }, last] : [...r, { role: "activity", text: e.text! }];
          });
          onActivity?.(e.text);
        }
      });
      patchLast((m) => ({ ...m, streaming: false }));
      onStatusChange?.(); // chat may have woken a down instance
    } catch (err) {
      patchLast((m) => ({ ...m, streaming: false }));
      setRows((r) => [...r, { role: "activity", text: `error: ${errMsg(err, "chat failed")}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="chat">
      <div className="chat-log" ref={logRef}>
        {rows.length === 0 && <div className="small muted pretty">{instanceId == null ? "no agent yet — press run agent; the agent appears with its first event." : empty}</div>}
        {rows.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="chat-user"><span className="accent">❯ </span>{m.text}</div>
          ) : m.role === "agent" ? (
            <div key={i} className="chat-agent"><Rich>{m.text}</Rich>{m.streaming && <span className="cursor">&nbsp;</span>}</div>
          ) : (
            <div key={i} className="chat-act">→ {m.text}</div>
          ),
        )}
      </div>
      <div className="prompt">
        <span className="sigil">❯</span>
        <input
          value={input}
          placeholder={instanceId == null ? "no agent yet" : busy ? "agent is working…" : "message the agent…"}
          disabled={busy || instanceId == null}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="btn flat" disabled={busy || !input.trim() || instanceId == null} onClick={send}>
          send
        </button>
      </div>
    </div>
  );
}
