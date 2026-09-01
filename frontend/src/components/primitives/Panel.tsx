import type { CSSProperties, ReactNode } from "react";
import { toneVar, type Tone } from "@/lib/tone.ts";
import styles from "./Panel.module.css";

export interface PanelProps {
  /** Background surface. `panel` is the default card, `panel2` is inset. */
  variant?: "panel" | "panel2";
  /** Softer border for secondary cards. */
  soft?: boolean;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}

/** Bordered surface card — the base container for every boxed section. */
export function Panel({ variant = "panel", soft = false, className, style, children }: PanelProps) {
  return (
    <div
      className={[styles.panel, soft ? styles.soft : "", className].filter(Boolean).join(" ")}
      style={{ background: `var(--${variant})`, ...style }}
    >
      {children}
    </div>
  );
}

export interface PanelHeaderProps {
  /** Leading glyph (e.g. "◈", "$_"). */
  icon?: ReactNode;
  iconTone?: Tone;
  title: ReactNode;
  /** Right-aligned content (counts, links, actions). */
  right?: ReactNode;
  className?: string;
}

/** Standard panel header: glyph + spaced-out title + optional right slot. */
export function PanelHeader({ icon, iconTone = "amber", title, right, className }: PanelHeaderProps) {
  return (
    <div className={[styles.header, className].filter(Boolean).join(" ")}>
      {icon != null && <span style={{ color: toneVar(iconTone) }}>{icon}</span>}
      <span className={styles.title}>{title}</span>
      {right != null && <span className={styles.right}>{right}</span>}
    </div>
  );
}
