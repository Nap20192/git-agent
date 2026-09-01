import type { ReactNode } from "react";
import { toneVar, type Tone } from "@/lib/tone.ts";
import styles from "./Badge.module.css";

export interface BadgeProps {
  tone?: Tone;
  /** Outlined pill (border + tone text) vs plain tone text. */
  outline?: boolean;
  uppercase?: boolean;
  children: ReactNode;
}

/** Small status/severity pill. */
export function Badge({ tone = "muted", outline = true, uppercase = false, children }: BadgeProps) {
  const color = toneVar(tone);
  return (
    <span
      className={[styles.badge, uppercase ? styles.upper : ""].filter(Boolean).join(" ")}
      style={{ color, border: outline ? `1px solid ${color}` : "none" }}
    >
      {children}
    </span>
  );
}
