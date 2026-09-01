import styles from "./Tabs.module.css";

export interface TabItem {
  id: string;
  label: string;
  /** Optional trailing count/badge. */
  badge?: string | number;
  disabled?: boolean;
}

export interface TabsProps {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
}

/** Terminal-style tab strip: chips with an active underline. */
export function Tabs({ items, value, onChange }: TabsProps) {
  return (
    <div className={styles.strip} role="tablist">
      {items.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={t.id === value}
          disabled={t.disabled}
          className={[styles.tab, t.id === value ? styles.active : ""].filter(Boolean).join(" ")}
          onClick={() => !t.disabled && onChange(t.id)}
        >
          {t.label}
          {t.badge != null && <span className={styles.badge}>{t.badge}</span>}
        </button>
      ))}
    </div>
  );
}
