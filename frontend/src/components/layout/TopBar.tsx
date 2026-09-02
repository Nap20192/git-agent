import { NavLink, useNavigate } from "react-router-dom";
import { SCREENS } from "@/app/screens.ts";
import { useTheme } from "@/lib/theme.ts";
import styles from "./TopBar.module.css";

/** Top bar: brand (→ runs), screen tabs, new-run action, clock. Route-driven,
 *  no global run state — the run detail screen owns its own live readouts. */
export function TopBar() {
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const clock = new Date().toLocaleTimeString("en-GB");

  return (
    <div className={styles.bar}>
      <div className={styles.brand} onClick={() => navigate("/runs")}>
        <span style={{ fontSize: 13 }}>◆</span>
        <span>git-agent</span>
        <span style={{ opacity: 0.7 }}>_</span>
      </div>

      <div className={styles.tabs}>
        {SCREENS.map((s) => (
          <NavLink
            key={s.id}
            to={s.path}
            className={({ isActive }) => [styles.tab, isActive ? styles.tabActive : ""].join(" ")}
          >
            <span className={styles.tabNum}>{s.num}</span>
            <span>{s.label}</span>
          </NavLink>
        ))}
      </div>

      <div style={{ flex: 1 }} />

      <div className={styles.newRun} onClick={() => navigate("/runs?new=1")}>
        ❯ new run
      </div>
      <button
        type="button"
        className={styles.theme}
        onClick={toggle}
        title={`switch to ${theme === "dark" ? "light" : "dark"} theme`}
      >
        {theme === "dark" ? "☀" : "☾"}
      </button>
      <div className={styles.meta}>
        <span style={{ color: "var(--amber)" }}>{clock}</span>
      </div>
    </div>
  );
}
