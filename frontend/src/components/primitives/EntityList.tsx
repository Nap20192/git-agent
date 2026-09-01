import type { ReactNode } from "react";
import styles from "./EntityList.module.css";

export interface Column<T> {
  id: string;
  header: ReactNode;
  /** CSS grid track for this column, e.g. "2fr" | "120px". */
  width: string;
  render: (row: T) => ReactNode;
  align?: "left" | "right";
}

export interface EntityListProps<T> {
  columns: Column<T>[];
  rows: T[];
  keyOf: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** Highlight the selected row. */
  selectedKey?: string | null;
  empty?: ReactNode;
}

/** Generic list-page table: typed columns, row click, empty state. Backs the
 *  runs / connections / sandboxes / skills lists. */
export function EntityList<T>({ columns, rows, keyOf, onRowClick, selectedKey, empty }: EntityListProps<T>) {
  const template = columns.map((c) => c.width).join(" ");
  if (rows.length === 0 && empty != null) return <div className={styles.empty}>{empty}</div>;
  return (
    <div className={styles.table}>
      <div className={styles.head} style={{ gridTemplateColumns: template }}>
        {columns.map((c) => (
          <span key={c.id} style={{ textAlign: c.align ?? "left" }}>
            {c.header}
          </span>
        ))}
      </div>
      {rows.map((row) => {
        const k = keyOf(row);
        return (
          <div
            key={k}
            className={[styles.row, onRowClick ? styles.clickable : "", k === selectedKey ? styles.selected : ""]
              .filter(Boolean)
              .join(" ")}
            style={{ gridTemplateColumns: template }}
            onClick={() => onRowClick?.(row)}
          >
            {columns.map((c) => (
              <span key={c.id} className={styles.cell} style={{ textAlign: c.align ?? "left" }}>
                {c.render(row)}
              </span>
            ))}
          </div>
        );
      })}
    </div>
  );
}
