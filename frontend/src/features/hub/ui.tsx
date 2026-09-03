/** Shared hub UI bits: status-bar context, drawer, tiny formatters. Styles live
 *  in styles/global.css (class vocabulary from docs/design/git-agent-hub.dc.html). */
import { createContext, useContext, useEffect, type ReactNode } from "react";

/* ── status bar context ───────────────────────────────────────────── */
export interface Shell {
  /** Status-bar message ("webhook: push …", errors, results). */
  say: (msg: string) => void;
  /** Status-bar context chip text ("owner/name · #id" or "hub"). */
  setCtx: (ctx: string | null) => void;
  /** Top-bar «● live feed» — an SSE stream is attached. */
  setLive: (on: boolean) => void;
}
export const ShellCtx = createContext<Shell>({ say: () => {}, setCtx: () => {}, setLive: () => {} });
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
