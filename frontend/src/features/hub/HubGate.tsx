/** Auth gate + app frame. GET /api/me decides: 401 → sign-in (OAuth only),
 *  ok → top bar (brand, repos/builds tabs, live dot, theme, user) + status bar
 *  (identity chip, context, message, position, clock) around the screen. */
import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { UnauthorizedError, useHubApi, type Me, type Provider } from "@/api/hub";
import { useHubRepositories, useInstances, useMe } from "@/hooks";
import { useTheme } from "@/lib/theme.ts";
import { ShellCtx, type Shell } from "./ui.tsx";

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 15000);
    return () => clearInterval(t);
  }, []);
  return now.toTimeString().slice(0, 5);
}

export function HubGate() {
  const meQ = useMe();
  if (meQ.loading) return <div className="app gate">loading…</div>;
  if (meQ.error instanceof UnauthorizedError) return <SignIn />;
  if (meQ.error) {
    return (
      <div className="app gate">
        <span className="err">can't reach the hub — {meQ.error.message}. check that the backend is running, then reload.</span>
      </div>
    );
  }
  return <Frame me={meQ.data!} />;
}

function SignIn() {
  const api = useHubApi();
  const { label, toggle } = useTheme();
  const clock = useClock();
  return (
    <div className="app" style={{ padding: "20px 20px 5px" }}>
      <div className="head" style={{ alignItems: "center", height: 34 }}>
        <div style={{ fontWeight: 700 }}>
          git-agent<span className="accent">_</span> <span className="muted" style={{ fontWeight: 400 }}>hub</span>
        </div>
        <button className="btn" onClick={toggle}>
          {label}
        </button>
      </div>
      <div style={{ flex: 1, display: "flex", alignItems: "center" }}>
        <div className="panel elev" style={{ padding: "28px 20px 16px", width: 440, marginLeft: "calc(50% - 220px)" }}>
          <span className="plabel" style={{ left: 12 }}>sign in</span>
          <p className="comment pretty" style={{ marginBottom: 16 }}>
            the hub connects a repository, installs a webhook and raises one long-lived agent per repo. sign in with the provider that hosts the code.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {(["github", "gitlab"] as Provider[]).map((p, i) => (
              <button
                key={p}
                className={`btn lg${i === 0 ? " primary" : ""}`}
                style={{ textAlign: "left", display: "flex", justifyContent: "space-between" }}
                onClick={() => api.login(p)}
              >
                <span>❯ continue with {p}</span>
                <span>→</span>
              </button>
            ))}
          </div>
          <div className="small muted" style={{ marginTop: 16 }}>oauth only · the hub never sees a password · keys are stored masked</div>
        </div>
      </div>
      <div className="small muted" style={{ height: 22, display: "flex", alignItems: "center" }}>hub 0.1 · {clock}</div>
    </div>
  );
}

const SCREEN_NAMES: Record<string, string> = { dash: "dash", repos: "repositories", builds: "builds", account: "account", instances: "playground" };

function Frame({ me }: { me: Me }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { label, toggle } = useTheme();
  const clock = useClock();
  const [msg, setMsg] = useState("ready");
  const [ctx, setCtx] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const reposQ = useHubRepositories();
  const instancesQ = useInstances();
  const shell = useMemo<Shell>(() => ({ say: setMsg, setCtx, setLive }), []);

  const seg = pathname.split("/")[1] || "repos";
  const screen = pathname.startsWith("/repos/") ? "repository" : (SCREEN_NAMES[seg] ?? seg);
  const ident = me.identities[0];
  const running = (instancesQ.data ?? []).filter((i) => i.status === "running").length;

  return (
    <ShellCtx.Provider value={shell}>
      <div className="app">
        <div className="topbar">
          <button className="brand" onClick={() => navigate("/repos")}>
            git-agent<span className="accent">_</span>
          </button>
          {[
            ["repositories", "/repos"],
            ["builds", "/builds"],
            ["dash", "/dash"],
          ].map(([l, to]) => (
            <NavLink key={to} to={to} className={({ isActive }) => `barbtn${isActive || (to === "/repos" && seg === "instances") ? " active" : ""}`}>
              {l}
            </NavLink>
          ))}
          <div style={{ flex: 1 }} />
          {live && (
            <div className="live">
              <span className="accent pulse" style={{ marginRight: 6 }}>●</span>live feed
            </div>
          )}
          <button className="barbtn right" onClick={toggle}>
            {label}
          </button>
          <button className="barbtn right" onClick={() => navigate("/account")}>
            {me.displayName}
          </button>
        </div>
        <div className="main">
          <Outlet />
        </div>
        <div className="statusbar">
          <span className="chip">{ident ? `${ident.username}@${ident.provider}` : me.displayName}</span>
          <span className="ctx">{ctx ?? "hub"}</span>
          <span className="msg">{msg}</span>
          <span style={{ flex: 1 }} />
          <span className="pos">
            {screen} · {(reposQ.data ?? []).length} repos · {running} running
          </span>
          <span className="clock">{clock}</span>
        </div>
      </div>
    </ShellCtx.Provider>
  );
}
