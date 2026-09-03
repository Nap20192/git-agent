/** Agent text on screen: markdown (GFM) with the important bits highlighted
 *  (severity words, CWE/CVE ids, file paths) and a clamp for long content.
 *  Used for chat replies, Отчёты, self-reports, work-log text, findings. */
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Long content collapses to `lines`; a toggle reveals the rest. */
export function Clamp({ lines = 14, children }: { lines?: number; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [long, setLong] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) setLong(el.scrollHeight > el.clientHeight + 1);
  }, [children, open]);
  return (
    <div>
      <div ref={ref} className={open ? "" : "clamp"} style={open ? undefined : ({ "--lines": lines } as React.CSSProperties)}>{children}</div>
      {(long || open) && (
        <button className="btn xs" style={{ marginTop: 4 }} onClick={() => setOpen((o) => !o)}>{open ? "collapse" : "show all"}</button>
      )}
    </div>
  );
}

/* ── markdown with important bits highlighted ──────────────────────── */
// severities → colour, CWE/CVE ids → chip, file paths (with :line) → underline
const HL = /(\b(?:critical|high|medium|low)\b)|(\bC(?:WE|VE)-\d[\d-]*\b)|((?:[\w.-]+\/)+[\w.-]+(?::\d+(?:-\d+)?)?)/gi;
const cls = (m: RegExpExecArray) => (m[1] ? `hl sev-${m[1].toLowerCase()}` : m[2] ? "hl id" : "hl path");

/** remark plugin: split text nodes on HL, wrap matches in <mark class=…>. */
function remarkHighlight() {
  const walk = (node: { type: string; value?: string; children?: unknown[] }) => {
    if (node.type === "inlineCode" || node.type === "code" || node.type === "link") return;
    if (!node.children) return;
    const out: unknown[] = [];
    for (const c of node.children as { type: string; value?: string; children?: unknown[] }[]) {
      if (c.type !== "text" || !c.value) { walk(c); out.push(c); continue; }
      let last = 0;
      HL.lastIndex = 0;
      for (let m = HL.exec(c.value); m; m = HL.exec(c.value)) {
        if (m.index > last) out.push({ type: "text", value: c.value.slice(last, m.index) });
        out.push({ type: "strong", data: { hName: "mark", hProperties: { className: cls(m) } }, children: [{ type: "text", value: m[0] }] });
        last = m.index + m[0].length;
      }
      out.push(last === 0 ? c : { type: "text", value: c.value.slice(last) });
    }
    node.children = out;
  };
  return walk;
}

export function Rich({ children }: { children: string }) {
  return (
    <div className="rich">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkHighlight]}>{children}</ReactMarkdown>
    </div>
  );
}
