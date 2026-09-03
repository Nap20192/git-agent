/** Auth gate for hub screens (Railway model: no passwords, OAuth only).
 *  GET /api/me decides: 401 → sign-in card, ok → the screen. */
import { Outlet } from "react-router-dom";
import { UnauthorizedError, useHubApi, type Provider } from "@/api/hub";
import { useMe } from "@/hooks";
import { Button, Panel } from "@/components/primitives";
import styles from "./hub.module.css";

export function HubGate() {
  const meQ = useMe();

  if (meQ.loading) return <div className={styles.gate}>loading…</div>;
  if (meQ.error instanceof UnauthorizedError) return <SignIn onDone={meQ.reload} />;
  if (meQ.error) {
    return (
      <div className={styles.gate}>
        <span style={{ color: "var(--crit)", fontSize: 12 }}>hub unreachable: {meQ.error.message}</span>
      </div>
    );
  }
  return <Outlet />;
}

function SignIn({ onDone }: { onDone: () => void }) {
  const api = useHubApi();
  const login = (provider: Provider) => api.login(provider).then(onDone);

  return (
    <div className={styles.gate}>
      <Panel className={styles.gateCard}>
        <h1 className={styles.gateTitle}>◆ git-agent hub</h1>
        <p className={styles.gateBlurb}>
          connect a git identity to monitor repositories. No passwords — sessions ride on your provider account.
        </p>
        <div className={styles.gateButtons}>
          <Button variant="primary" onClick={() => login("github")}>
             sign in with GitHub
          </Button>
          <Button variant="outline" onClick={() => login("gitlab")}>
            ⌾ sign in with GitLab
          </Button>
        </div>
      </Panel>
    </div>
  );
}
