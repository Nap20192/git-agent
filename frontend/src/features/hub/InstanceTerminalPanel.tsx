/** Stream-console into the Экземпляр's sandbox (xterm.js over the hub SSE
 *  proxy, POST /instances/{id}/terminal). Not a PTY: each command runs in a
 *  fresh shell; only the working directory carries over between commands.
 *  The line discipline (echo, backspace, prompt) is local to this component. */
import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { useHubApi } from "@/api/hub";
import { Panel, PanelHeader } from "@/components/primitives";
import styles from "./terminal.module.css";

function cssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function InstanceTerminalPanel({
  instanceId,
  running,
  hasSandbox,
}: {
  instanceId: number;
  /** Экземпляр status === "running" — the terminal only works on a raised agent. */
  running: boolean;
  /** sandboxInstanceId != null — the user creates the sandbox in the UI; we never do. */
  hasSandbox: boolean;
}) {
  const api = useHubApi();
  const hostRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const ready = running && hasSandbox;

  useEffect(() => {
    if (!ready || !hostRef.current) return;
    const term = new Terminal({
      convertEol: true,
      cursorBlink: true,
      fontSize: 12,
      fontFamily: cssVar("--font-mono", "monospace"),
      theme: {
        background: cssVar("--bg-deep", "#050403"),
        foreground: cssVar("--text", "#dadada"),
        cursor: cssVar("--amber", "#ffaf00"),
        selectionBackground: cssVar("--subtle", "#2a2a2a"),
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(hostRef.current);
    fit.fit();
    const observer = new ResizeObserver(() => fit.fit());
    observer.observe(hostRef.current);
    termRef.current = term;

    let line = "";
    let cwd: string | null = null;
    let busy = false;
    const prompt = () => term.write(`\x1b[38;5;179m${cwd ?? "sandbox"}\x1b[0m $ `);

    const run = async (command: string) => {
      busy = true;
      try {
        await api.terminal(instanceId, command, (e) => {
          if (e.kind === "output" && e.text) term.write(e.text + "\n");
          if (e.kind === "exit") {
            cwd = e.cwd ?? cwd;
            if (e.code != null && e.code !== 0) term.write(`\x1b[38;5;203mexit ${e.code}\x1b[0m\n`);
          }
          term.scrollToBottom();
        });
      } catch (err) {
        term.write(`\x1b[38;5;203m${err instanceof Error ? err.message : "terminal failed"}\x1b[0m\n`);
      }
      busy = false;
      prompt();
      term.scrollToBottom();
    };

    term.onData((data) => {
      if (busy) return; // no PTY behind — nothing to feed keystrokes into
      for (const ch of data) {
        if (ch === "\r") {
          term.write("\r\n");
          const command = line;
          line = "";
          if (command.trim()) void run(command);
          else prompt();
        } else if (ch === "\x7f") {
          if (line) {
            line = line.slice(0, -1);
            term.write("\b \b");
          }
        } else if (ch === "\x03") {
          term.write("^C\r\n");
          line = "";
          prompt();
        } else if (ch === "\x0c") {
          term.clear();
        } else if (ch >= " ") {
          line += ch;
          term.write(ch);
        }
      }
    });

    term.writeln("\x1b[38;5;242mstream console — each command runs in a fresh shell; cwd persists, env does not\x1b[0m");
    prompt();

    return () => {
      observer.disconnect();
      term.dispose();
      termRef.current = null;
    };
  }, [ready, instanceId, api]);

  return (
    <Panel className={styles.panel}>
      <PanelHeader
        icon=">_"
        title="TERMINAL — SANDBOX"
        right={
          ready ? (
            <button type="button" className={styles.clear} onClick={() => termRef.current?.clear()}>
              clear
            </button>
          ) : undefined
        }
      />
      {ready ? (
        <div className={styles.host} ref={hostRef} />
      ) : (
        <div className={styles.empty}>
          {!hasSandbox
            ? "No sandbox — create one for this Экземпляр in the UI to open the terminal."
            : "The agent is down — raise it (Run agent or send a chat message) to open the terminal."}
        </div>
      )}
    </Panel>
  );
}
