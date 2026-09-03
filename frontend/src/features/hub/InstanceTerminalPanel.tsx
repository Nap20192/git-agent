/** Stream-console into the Экземпляр's sandbox (POST /instances/{id}/terminal,
 *  SSE). Not a PTY: each command runs in a fresh shell; only cwd carries over.
 *  Output renders in xterm (ANSI-aware); the command line is the «cwd ❯» prompt
 *  below it, with ↑/↓ history. */
import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { useHubApi } from "@/api/hub";
import { errMsg } from "./ui.tsx";

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function InstanceTerminalPanel({ instanceId, running, hasSandbox, sandboxLabel }: { instanceId: number; running: boolean; hasSandbox: boolean; sandboxLabel: string }) {
  const api = useHubApi();
  const hostRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const [cwd, setCwd] = useState("/repo");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [hist, setHist] = useState<string[]>([]);
  const [hi, setHi] = useState(-1);
  const ready = running && hasSandbox;

  useEffect(() => {
    if (!ready || !hostRef.current) return;
    const term = new Terminal({
      convertEol: true,
      disableStdin: true,
      cursorStyle: "underline",
      fontSize: 13,
      fontWeight: 300,
      fontFamily: getComputedStyle(document.body).fontFamily,
      theme: { background: cssVar("--bg-elevated"), foreground: cssVar("--text"), cursor: cssVar("--accent"), selectionBackground: cssVar("--selection-bg") },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(hostRef.current);
    fit.fit();
    const observer = new ResizeObserver(() => fit.fit());
    observer.observe(hostRef.current);
    termRef.current = term;
    term.writeln(`\x1b[2msandbox ${sandboxLabel} · stdout+stderr merged · commands run in a fresh shell, cwd persists\x1b[0m`);
    return () => {
      observer.disconnect();
      term.dispose();
      termRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, instanceId]);

  const run = async () => {
    const cmd = input.trim();
    const term = termRef.current;
    if (!cmd || busy || !term) return;
    setInput("");
    setHist((h) => [cmd, ...h].slice(0, 100));
    setHi(-1);
    if (cmd === "clear") return term.clear();
    term.writeln(`\x1b[2m${cwd}\x1b[0m \x1b[38;2;255;175;0m❯\x1b[0m ${cmd}`);
    setBusy(true);
    try {
      await api.terminal(instanceId, cmd, (e) => {
        if (e.kind === "output" && e.text) term.write(e.text + "\n");
        if (e.kind === "exit") {
          if (e.cwd) setCwd(e.cwd);
          term.writeln(e.code != null && e.code !== 0 ? `\x1b[38;2;255;0;95m→ exit ${e.code}\x1b[0m` : `\x1b[2m→ exit ${e.code ?? "?"}\x1b[0m`);
        }
        term.scrollToBottom();
      });
    } catch (err) {
      term.writeln(`\x1b[38;2;255;0;95m${errMsg(err, "terminal failed")}\x1b[0m`);
    } finally {
      setBusy(false);
      term.scrollToBottom();
    }
  };

  return (
    <div className="term">
      {ready ? (
        <div className="term-host" ref={hostRef} />
      ) : (
        <div className="empty small" style={{ flex: 1 }}>
          {!hasSandbox ? "no sandbox yet — run the agent or send a chat message (the hub creates one), or create it on the timeline tab." : "the agent is down — raise it (run agent or send a chat message) to open the terminal."}
        </div>
      )}
      <div className="prompt">
        <span className="sigil comment">{cwd} <span className="accent">❯</span></span>
        <input
          value={input}
          disabled={!ready || busy}
          placeholder={busy ? "running…" : "ls -la"}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") run();
            else if (e.key === "ArrowUp" && hist.length) {
              const n = Math.min(hi + 1, hist.length - 1);
              setHi(n);
              setInput(hist[n]);
              e.preventDefault();
            } else if (e.key === "ArrowDown") {
              const n = Math.max(hi - 1, -1);
              setHi(n);
              setInput(n < 0 ? "" : hist[n]);
              e.preventDefault();
            }
          }}
        />
      </div>
    </div>
  );
}
