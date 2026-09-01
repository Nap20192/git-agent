/**
 * Tone system: a named color role maps to a CSS variable. Components take a
 * `tone` prop instead of raw colors so theming stays centralized in tokens.css.
 */
export type Tone =
  | "text"
  | "muted"
  | "dim"
  | "comment"
  | "amber"
  | "burnt"
  | "blue"
  | "crit"
  | "high"
  | "med"
  | "low"
  | "info";

export function toneVar(tone: Tone): string {
  return `var(--${tone})`;
}
