import type { InputHTMLAttributes, ReactNode } from "react";
import styles from "./TextInput.module.css";

export interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Leading glyph inside the field, e.g. "❯" or "⎇". */
  glyph?: ReactNode;
  /** Highlight the border (e.g. valid input ready to submit). */
  active?: boolean;
  /** Trailing slot (submit affordance, status). */
  trailing?: ReactNode;
}

/** Terminal-style prompt input with a leading glyph. */
export function TextInput({ glyph = "❯", active = false, trailing, className, ...rest }: TextInputProps) {
  return (
    <div className={[styles.wrap, active ? styles.active : "", className].filter(Boolean).join(" ")}>
      {glyph != null && <span className={styles.glyph}>{glyph}</span>}
      <input className={styles.input} {...rest} />
      {trailing}
    </div>
  );
}
