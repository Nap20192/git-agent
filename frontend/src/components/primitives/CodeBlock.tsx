import { useState } from "react";
import { toneVar, type Tone } from "@/lib/tone.ts";
import styles from "./CodeBlock.module.css";

export interface CodeBlockProps {
  children: string;
  /** Left accent bar tone. */
  accent?: Tone;
  /** Show a copy button. */
  copyable?: boolean;
  /** Small caption above the block. */
  label?: string;
}

/** Monospace scrollable code/prompt block with an optional copy button. */
export function CodeBlock({ children, accent, copyable = true, label }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const accentColor = accent ? toneVar(accent) : "var(--border-soft)";
  const copy = () => {
    navigator.clipboard?.writeText(children).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  };
  return (
    <div className={styles.wrap}>
      {(label || copyable) && (
        <div className={styles.bar}>
          {label && <span className={styles.label}>{label}</span>}
          {copyable && (
            <button className={styles.copy} onClick={copy}>
              {copied ? "✓ copied" : "⧉ copy"}
            </button>
          )}
        </div>
      )}
      <pre className={styles.pre} style={{ borderLeft: `2px solid ${accentColor}` }}>
        {children}
      </pre>
    </div>
  );
}
