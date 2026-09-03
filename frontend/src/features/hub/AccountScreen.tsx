/** Account: identities (Связки — linked git identities; unlink / link more),
 *  appearance (theme), session (sign out). */
import { useHubApi, type Provider } from "@/api/hub";
import { useHubRepositories, useMe } from "@/hooks";
import { useTheme } from "@/lib/theme.ts";
import { Panel, ago, errMsg, useScreenCtx, useShell } from "./ui.tsx";

export function AccountScreen() {
  const api = useHubApi();
  const { say } = useShell();
  const { theme, label, toggle } = useTheme();
  const meQ = useMe();
  const reposQ = useHubRepositories();
  const me = meQ.data;
  useScreenCtx(null);

  const unlink = async (id: number, provider: string) => {
    if (!window.confirm(`unlink ${provider}? its connected repositories stay, but the hub loses that account's access.`)) return;
    try {
      await api.deleteIdentity(id);
      say(`unlinked ${provider}`);
      meQ.reload();
    } catch (e) {
      say(errMsg(e, "unlink failed"));
    }
  };
  const logout = async () => {
    await api.logout();
    window.location.assign("/repos"); // full reload → HubGate re-checks /api/me and shows sign-in
  };

  return (
    <div className="screen" style={{ gap: 20, maxWidth: 720 }}>
      <div>
        <h1>{me?.displayName ?? "…"}</h1>
        <div className="sub">user #{me?.id ?? "—"} · {me?.identities.length ?? 0} identities</div>
      </div>
      <Panel label="identities">
        {(me?.identities ?? []).map((i) => (
          <div key={i.id} className="lrow" style={{ padding: 12, alignItems: "center" }}>
            <div>
              <b>{i.provider}</b> <span className="comment">{i.username}</span>
              <div className="small muted">linked {ago(i.createdAt)} · {(reposQ.data ?? []).filter((r) => r.identityId === i.id).length} connected repos</div>
            </div>
            <button className="btn sm danger" onClick={() => unlink(i.id, i.provider)}>unlink</button>
          </div>
        ))}
        {me && me.identities.length === 0 && <div className="empty small">no identities linked.</div>}
        <div className="row" style={{ padding: 12, background: "var(--bg-elevated)" }}>
          {(["github", "gitlab"] as Provider[]).map((p) => (
            <button key={p} className="btn" onClick={() => api.login(p)}>+ link {p}</button>
          ))}
        </div>
      </Panel>
      <Panel label="appearance" className="pad">
        <div className="kv" style={{ alignItems: "center" }}>
          <span>theme <span className="muted">· {theme}</span></span>
          <button className="btn" onClick={toggle}>{label}</button>
        </div>
      </Panel>
      <Panel label="session" className="pad">
        <div className="kv" style={{ alignItems: "center" }}>
          <span className="comment small">watchers keep running after sign-out; only this browser session ends.</span>
          <button className="btn" onClick={logout}>sign out →</button>
        </div>
      </Panel>
    </div>
  );
}
