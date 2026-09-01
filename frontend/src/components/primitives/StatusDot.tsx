import { toneVar, type Tone } from "@/lib/tone.ts";

export interface StatusDotProps {
  tone?: Tone;
  /** Pulse animation for live/running state. */
  pulse?: boolean;
  /** Soft glow halo. */
  glow?: boolean;
  size?: number;
}

/** A small colored status dot with optional pulse + glow. */
export function StatusDot({ tone = "low", pulse = false, glow = true, size = 7 }: StatusDotProps) {
  const color = toneVar(tone);
  return (
    <span
      style={{
        width: size,
        height: size,
        background: color,
        borderRadius: 999,
        flexShrink: 0,
        display: "inline-block",
        boxShadow: glow ? `0 0 6px ${color}` : "none",
        animation: pulse ? "vk-pulse 1.1s ease-in-out infinite" : "none",
      }}
    />
  );
}
