import { Outlet } from "react-router-dom";
import { TopBar } from "./TopBar.tsx";
import { StatusBar } from "./StatusBar.tsx";
import styles from "./AppShell.module.css";

/** App frame: fixed top bar + status bar with the active screen between them. */
export function AppShell() {
  return (
    <div className={styles.shell}>
      <TopBar />
      <div className={styles.body}>
        <Outlet />
      </div>
      <StatusBar />
    </div>
  );
}
