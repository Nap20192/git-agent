import type { ReactNode } from "react";
import { useEffect } from "react";
import styles from "./Drawer.module.css";

export interface DrawerProps {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  width?: number;
  children: ReactNode;
}

/** Right-side overlay panel for detail/create forms. Esc + backdrop close. */
export function Drawer({ open, title, onClose, width = 420, children }: DrawerProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.panel} style={{ width }} onClick={(e) => e.stopPropagation()}>
        <div className={styles.head}>
          <span className={styles.title}>{title}</span>
          <button className={styles.close} onClick={onClose}>
            ✕
          </button>
        </div>
        <div className={styles.body}>{children}</div>
      </div>
    </div>
  );
}
