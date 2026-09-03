/** Auth gate + theme shell for hub screens. Everything under it renders inside
 *  the Claude design island (data-theme="claude"). GET /api/me decides:
 *  401 → sign-in card (Railway model: OAuth only, no passwords), ok → screen. */
import { Outlet } from "react-router-dom";
import { UnauthorizedError, useHubApi, type Provider } from "@/api/hub";
import { useMe } from "@/hooks";
import { Button, Panel } from "@/components/primitives";
import styles from "./hub.module.css";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div data-theme="claude" className={styles.shell}>
      {children}
    </div>
  );
}

export function HubGate() {
  const meQ = useMe();

  if (meQ.loading) {
    return (
      <Shell>
        <div className={styles.gate}>loading…</div>
      </Shell>
    );
  }
  if (meQ.error instanceof UnauthorizedError) {
    return (
      <Shell>
        <SignIn onDone={meQ.reload} />
      </Shell>
    );
  }
  if (meQ.error) {
    return (
      <Shell>
        <div className={styles.gate}>
          <span style={{ color: "var(--crit)", fontSize: 13 }}>
            Can't reach the hub — {meQ.error.message}. Check that the backend is running, then reload.
          </span>
        </div>
      </Shell>
    );
  }
  return (
    <Shell>
      <Outlet />
    </Shell>
  );
}

function SignIn({ onDone }: { onDone: () => void }) {
  const api = useHubApi();
  const login = (provider: Provider) => api.login(provider).then(onDone);

  return (
    <div className={styles.gate}>
      <Panel className={styles.gateCard}>
        <div className={styles.gateMark}>✳</div>
        <h1 className={styles.gateTitle}>An agent for every repository</h1>
        <p className={styles.gateBlurb}>
          Connect a repository and its agent starts watching: every push lands in its journal, findings surface in
          reports, and you can ask it anything. Sign in with the account that owns your repos.
        </p>
        <div className={styles.gateButtons}>
          <Button variant="primary" onClick={() => login("github")}>
            Continue with GitHub
          </Button>
          <Button variant="outline" onClick={() => login("gitlab")}>
            Continue with GitLab
          </Button>
        </div>
      </Panel>
    </div>
  );
}
