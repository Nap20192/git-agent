/** Chat with an agent Экземпляр — ChatGPT-style: the transcript is persisted by
 *  the hub (GET /instances/{id}/messages: user/agent messages + cards of the
 *  turns run on Событий), loaded on open with "earlier" paging; a reply
 *  streams token by token over the chat SSE, a `message` frame replaces the
 *  streamed text with the canonical one; stop cancels the turn (same as the
 *  playground stop). Multi-line input: Enter sends, Shift+Enter breaks a line.
 *  Renders log + prompt only — the host wraps it (panel or tab box). */
import { useEffect, useRef, useState } from "react";
import { useHubApi, type ChatEvent, type ChatMessage } from "@/api/hub";
import { Rich } from "./rich.tsx";
import { errMsg, sha } from "./ui.tsx";

interface Row {
  key: string;
  role: "user" | "agent" | "activity" | "event";
  text: string;
  ts?: string;
  streaming?: boolean;
  msg?: ChatMessage;
}

const lastStreaming = (r: Row[]) => {
  for (let i = r.length - 1; i >= 0; i--) if (r[i].streaming) return i;
  return -1;
};

const fromMessage = (m: ChatMessage): Row => ({ key: `m${m.id}`, role: m.role, text: m.text ?? "", ts: m.ts, msg: m });

const when = (iso?: string) => {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

function EventCard({ m }: { m: ChatMessage }) {
  const label = m.action ? `${m.action} @ ${sha(m.commitSha)}` : "chat turn";
  const tail = m.status === "failed" ? `failed${m.text ? ` — ${m.text}` : ""}` : m.status === "finished" ? `finished · ${m.findingsCount ?? 0} finding${m.findingsCount === 1 ? "" : "s"}` : "started";
  return (
    <div className={`chat-event${m.status === "failed" ? " bad" : ""}`} title={m.traceId ? `trace ${m.traceId}` : undefined}>
      → {label} · {tail}
    </div>
  );
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
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true); // auto-scroll only while the reader is at the bottom
  const seq = useRef(0);

  // history: (re)load when the instance changes
  useEffect(() => {
    setRows([]);
    setMore(false);
    if (instanceId == null) return;
    let alive = true;
    setLoading(true);
    api
      .listMessages(instanceId)
      .then((h) => {
        if (!alive) return;
        setRows(h.messages.map(fromMessage));
        setMore(h.more);
        stickRef.current = true;
      })
      .catch((e) => alive && setRows([{ key: "err", role: "activity", text: `history unavailable: ${errMsg(e, "load failed")}` }]))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [api, instanceId]);

  useEffect(() => {
    if (stickRef.current) logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [rows]);

  const loadEarlier = async () => {
    const first = rows.find((r) => r.msg)?.msg;
    if (instanceId == null || !first || loading) return;
    setLoading(true);
    try {
      const h = await api.listMessages(instanceId, { before: first.id });
      const el = logRef.current;
      const keep = el ? el.scrollHeight - el.scrollTop : 0;
      stickRef.current = false;
      setRows((r) => [...h.messages.map(fromMessage), ...r]);
      setMore(h.more);
      requestAnimationFrame(() => { if (el) el.scrollTop = el.scrollHeight - keep; });
    } catch (e) {
      setRows((r) => [{ key: `e${seq.current++}`, role: "activity", text: `earlier messages unavailable: ${errMsg(e, "load failed")}` }, ...r]);
    } finally {
      setLoading(false);
    }
  };

  const send = async () => {
    const message = input.trim();
    if (!message || busy || instanceId == null) return;
    setInput("");
    setBusy(true);
    stickRef.current = true;
    const agentKey = `a${seq.current++}`;
    setRows((r) => [...r, { key: `u${seq.current++}`, role: "user", text: message, ts: new Date().toISOString() }, { key: agentKey, role: "agent", text: "", streaming: true }]);
    // the streaming agent row stays last; activity lands above it
    const patchStreaming = (fn: (m: Row) => Row) =>
      setRows((r) => {
        const i = lastStreaming(r);
        return i < 0 ? r : [...r.slice(0, i), fn(r[i]), ...r.slice(i + 1)];
      });
    const insertAbove = (row: Row) =>
      setRows((r) => {
        const i = lastStreaming(r);
        return i < 0 ? [...r, row] : [...r.slice(0, i), row, ...r.slice(i)];
      });
    try {
      await api.chat(instanceId, message, (e: ChatEvent) => {
        if (e.kind === "token" && e.text) patchStreaming((m) => ({ ...m, text: m.text + e.text }));
        if (e.kind === "message" && e.text) {
          // canonical message: replaces the streamed text; a later one opens a new row
          const text = e.text;
          setRows((r) => {
            const i = lastStreaming(r);
            if (i < 0) return r;
            const done = { ...r[i], text, streaming: false, ts: new Date().toISOString() };
            return [...r.slice(0, i), done, { key: `a${seq.current++}`, role: "agent", text: "", streaming: true }, ...r.slice(i + 1)];
          });
        }
        if (e.kind === "activity" && e.text) {
          insertAbove({ key: `x${seq.current++}`, role: "activity", text: e.text });
          onActivity?.(e.text);
        }
      });
      onStatusChange?.(); // chat may have woken a down instance
    } catch (err) {
      insertAbove({ key: `x${seq.current++}`, role: "activity", text: `error: ${errMsg(err, "chat failed")}` });
    } finally {
      // drop an empty trailing streaming row, finalize a non-empty one
      setRows((r) => r.flatMap((m) => (m.streaming ? (m.text ? [{ ...m, streaming: false, ts: m.ts ?? new Date().toISOString() }] : []) : [m])));
      setBusy(false);
      setStopping(false);
    }
  };

  const stop = async () => {
    if (instanceId == null || stopping) return;
    setStopping(true);
    try {
      await api.stopInstance(instanceId);
    } catch (err) {
      insertAct(`stop failed: ${errMsg(err, "stop failed")}`);
      setStopping(false);
    }
  };
  const insertAct = (text: string) => setRows((r) => [...r, { key: `x${seq.current++}`, role: "activity", text }]);

  const onScroll = () => {
    const el = logRef.current;
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  return (
    <div className="chat">
      <div className="chat-log" ref={logRef} onScroll={onScroll}>
        {more && (
          <button className="btn xs" style={{ alignSelf: "center" }} disabled={loading} onClick={loadEarlier}>{loading ? "loading…" : "↑ earlier messages"}</button>
        )}
        {rows.length === 0 && (
          <div className="small muted pretty">{instanceId == null ? "no agent yet — press run agent; the agent appears with its first event." : loading ? "loading history…" : empty}</div>
        )}
        {rows.map((m) =>
          m.role === "user" ? (
            <div key={m.key} className="chat-user"><span className="accent">❯ </span>{m.text}{m.ts && <span className="chat-time">{when(m.ts)}</span>}</div>
          ) : m.role === "agent" ? (
            <div key={m.key} className="chat-agent"><Rich>{m.text}</Rich>{m.streaming && <span className="cursor">&nbsp;</span>}{!m.streaming && m.ts && <span className="chat-time">{when(m.ts)}</span>}</div>
          ) : m.role === "event" && m.msg ? (
            <EventCard key={m.key} m={m.msg} />
          ) : (
            <div key={m.key} className="chat-act">→ {m.text}</div>
          ),
        )}
      </div>
      <div className="prompt">
        <span className="sigil">❯</span>
        <textarea
          rows={1}
          value={input}
          placeholder={instanceId == null ? "no agent yet" : busy ? "agent is working… (you can queue your next question)" : "message the agent · Enter to send, Shift+Enter for a new line"}
          disabled={instanceId == null}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        {busy ? (
          <button className="btn flat danger" disabled={stopping} onClick={stop}>{stopping ? "stopping…" : "■ stop"}</button>
        ) : (
          <button className="btn flat" disabled={!input.trim() || instanceId == null} onClick={send}>send</button>
        )}
      </div>
    </div>
  );
}
