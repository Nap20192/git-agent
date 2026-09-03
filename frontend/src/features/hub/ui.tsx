/** Shared hub UI bits: status-bar context, drawer, tiny formatters. Styles live
 *  in styles/global.css (class vocabulary from docs/design/git-agent-hub.dc.html). */
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, traceTail } from "@/api/hub";

/* ── status bar context ───────────────────────────────────────────── */
export interface Shell {
  /** Status-bar message ("webhook: push …", errors, results). */
  say: (msg: string) => void;
  /** Status-bar context chip text ("owner/name · #id" or "hub"). */
  setCtx: (ctx: string | null) => void;
  /** Top-bar «● live feed» — an SSE stream is attached. */
  setLive: (on: boolean) => void;
  /** Surface a failed call: backend message + trace id in a banner over the screen (and the status bar). */
  fail: (e: unknown, fallback: string) => void;
}
export const ShellCtx = createContext<Shell>({ say: () => {}, setCtx: () => {}, setLive: () => {}, fail: () => {} });

/** What the error banner shows for one failed call. */
export interface ShellError {
  message: string;
  traceId: string;
  status: number;
}
export function toShellError(e: unknown, fallback: string): ShellError {
  if (e instanceof ApiError) return { message: e.message, traceId: e.traceId, status: e.status };
  return { message: e instanceof Error ? e.message : fallback, traceId: "", status: 0 };
}
export const useShell = () => useContext(ShellCtx);

/** Declares the status-bar context for the lifetime of a screen. */
export function useScreenCtx(ctx: string | null) {
  const { setCtx } = useShell();
  useEffect(() => {
    setCtx(ctx);
    return () => setCtx(null);
  }, [ctx, setCtx]);
}

/* ── drawer (right, 440px, esc/backdrop close) ────────────────────── */
export function Drawer({ open, title, onClose, children }: { open: boolean; title: ReactNode; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <div className="drawer">
        <div className="drawer-head">
          <b>{title}</b>
          <button className="btn sm" onClick={onClose}>
            esc
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </>
  );
}

/* ── panel with floating label ────────────────────────────────────── */
export function Panel({ label, dim, className = "", style, children }: { label: ReactNode; dim?: ReactNode; className?: string; style?: React.CSSProperties; children: ReactNode }) {
  return (
    <div className={`panel ${className}`} style={style}>
      <span className="plabel">
        {label}
        {dim != null && <span className="dim"> · {dim}</span>}
      </span>
      {children}
    </div>
  );
}

/* ── formatters ───────────────────────────────────────────────────── */
export function ago(iso?: string | null): string {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
export const sha = (x?: string | null) => (x ? x.slice(0, 7) : "—");
export const shortRef = (r?: string | null) => (r ? r.replace("refs/heads/", "").replace("refs/", "") : "—");
export const errMsg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

/** Status glyph: ● amber (pulsing when `pulse`) / ○ muted. */
export function Dot({ on, pulse }: { on: boolean; pulse?: boolean }) {
  return on ? <span className={`accent${pulse ? " pulse" : ""}`}>● </span> : <span className="muted">○ </span>;
}

/* ── error banner (backend message + trace id, dismissable) ───────── */
export function ErrorBanner({ err, onClose }: { err: ShellError; onClose: () => void }) {
  const { say } = useShell();
  return (
    <div className="banner err" role="alert">
      <span className="err" style={{ fontWeight: 700 }}>✗ {err.status ? `HTTP ${err.status}` : "error"}</span>
      <span className="pretty" style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{err.message}</span>
      {err.traceId && (
        <button
          className="btn sm"
          title={`${err.traceId} — the same id is in hub/runner logs and the LLM trace (click to copy)`}
          onClick={() => { void navigator.clipboard?.writeText(err.traceId); say(`copied trace ${err.traceId}`); }}
        >
          copy {traceTail(err.traceId)}
        </button>
      )}
      <button className="btn sm" onClick={onClose}>dismiss</button>
    </div>
  );
}

/* ── onboarding checklist (empty dashboard / repositories) ────────── */
export interface OnboardingState {
  llm: boolean;
  build: boolean;
  repo: boolean;
}
/** Three steps to a running agent, ticked from live data. `onConnect` opens the connect drawer. */
export function Onboarding({ state, onConnect }: { state: OnboardingState; onConnect?: () => void }) {
  const navigate = useNavigate();
  const go = (to: string) => (e: React.MouseEvent) => { e.preventDefault(); navigate(to); };
  const steps: { done: boolean; text: ReactNode; action: ReactNode }[] = [
    { done: state.llm, text: <>add an <b>llm connection</b> — api base, model, key</>, action: <a href="/builds" onClick={go("/builds")}>builds → llm connections</a> },
    { done: state.build, text: <>create a <b>build</b> and make it the default — it serves every repo without its own subscription</>, action: <a href="/builds" onClick={go("/builds")}>builds → new build</a> },
    { done: state.repo, text: <>connect a <b>repository</b> — your own (webhook) or any public one by url</>, action: onConnect ? <a href="/repos" onClick={(e) => { e.preventDefault(); onConnect(); }}>connect repository</a> : <a href="/repos" onClick={go("/repos")}>repositories</a> },
  ];
  const next = steps.findIndex((s) => !s.done);
  return (
    <Panel label="getting started" dim={`${steps.filter((s) => s.done).length}/${steps.length}`} className="elev">
      {steps.map((s, i) => (
        <div key={i} className="lrow" style={{ padding: "10px 12px", alignItems: "center", opacity: s.done ? 0.6 : 1 }}>
          <div>
            <span className={s.done ? "accent" : i === next ? "accent pulse" : "muted"}>{s.done ? "✓" : "○"} </span>
            <span className="muted">{i + 1}.</span> {s.text}
          </div>
          {!s.done && <span className="small" style={{ whiteSpace: "nowrap" }}>{s.action}</span>}
        </div>
      ))}
      <div className="small muted" style={{ padding: "8px 12px", background: "var(--bg-elevated)" }}>
        then open the repository and press <b>run agent</b> — the hub creates a sandbox instance for the agent and the runner picks the event up.
      </div>
    </Panel>
  );
}
