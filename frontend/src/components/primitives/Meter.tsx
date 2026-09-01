import { toneVar, type Tone } from "@/lib/tone.ts";

export interface MeterProps {
  /** 0-100. */
  pct: number;
  tone?: Tone;
  width?: number;
  height?: number;
  bordered?: boolean;
}

/** Thin horizontal fill bar (agent load, weakness weight). */
export function Meter({ pct, tone = "amber", width = 46, height = 5, bordered = true }: MeterProps) {
  return (
    <div
      style={{
        width,
        height,
        background: "var(--bg-deep)",
        border: bordered ? "1px solid var(--border-soft)" : "none",
        flexShrink: 0,
      }}
    >
      <div style={{ height: "100%", width: `${Math.max(0, Math.min(100, pct))}%`, background: toneVar(tone) }} />
    </div>
  );
}
