import type { ReactNode } from "react";
import { toneVar, type Tone } from "@/lib/tone.ts";
import styles from "./KeyValueList.module.css";

export interface KeyValueRow {
  key: string;
  value: ReactNode;
  tone?: Tone;
}

/** Aligned label/value rows (run meta, sandbox spec, connection detail). */
export function KeyValueList({ rows }: { rows: KeyValueRow[] }) {
  return (
    <div className={styles.list}>
      {rows.map((r, i) => (
        <div key={i} className={styles.row}>
          <span className={styles.k}>{r.key}</span>
          <span className={styles.v} style={r.tone ? { color: toneVar(r.tone) } : undefined}>
            {r.value}
          </span>
        </div>
      ))}
    </div>
  );
}
