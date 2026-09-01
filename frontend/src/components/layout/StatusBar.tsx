import { useLocation } from "react-router-dom";
import styles from "./StatusBar.module.css";

/** Bottom status line: mode chip + current route path. Route-driven. */
export function StatusBar() {
  const { pathname } = useLocation();
  const screen = pathname.replace(/^\//, "") || "runs";

  return (
    <div className={styles.bar}>
      <div className={styles.mode} style={{ background: "var(--low)" }}>
        ◆ git-agent
      </div>
      <div className={styles.path}>~/git-agent/{screen}</div>
      <div style={{ flex: 1 }} />
      <div className={styles.metrics}>
        <span style={{ color: "var(--dim)" }}>scan → parse → report</span>
      </div>
    </div>
  );
}
