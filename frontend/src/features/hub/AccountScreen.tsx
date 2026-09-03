/** Account: who am I + git identity links (Связки). Add another provider link
 *  or sign out; repo connection lives on the repos screen. */
import { useHubApi, type Identity, type Provider } from "@/api/hub";
import { useMe } from "@/hooks";
import { Badge, Button, EntityList } from "@/components/primitives";
import type { Column } from "@/components/primitives";
import styles from "./hub.module.css";

export function AccountScreen() {
  const api = useHubApi();
  const meQ = useMe();
  const me = meQ.data;

  const addIdentity = (provider: Provider) => api.login(provider).then(meQ.reload);
  const removeIdentity = async (id: number) => {
    await api.deleteIdentity(id);
    meQ.reload();
  };
  const logout = async () => {
    await api.logout();
    // full reload → HubGate re-checks /api/me and shows sign-in
    window.location.assign("/repos");
  };

  const columns: Column<Identity>[] = [
    {
      id: "provider",
      header: "PROVIDER",
      width: "1fr",
      render: (i) => <Badge tone={i.provider === "github" ? "text" : "burnt"}>{i.provider}</Badge>,
    },
    { id: "username", header: "USERNAME", width: "1.6fr", render: (i) => <span style={{ color: "var(--text)" }}>{i.username}</span> },
    {
      id: "created",
      header: "LINKED",
      width: "1.4fr",
      render: (i) => <span className={styles.cell}>{i.createdAt ? new Date(i.createdAt).toLocaleString() : "—"}</span>,
    },
    {
      id: "actions",
      header: "",
      width: "90px",
      align: "right",
      render: (i) => (
        <Button
          variant="ghost"
          onClick={(e) => {
            e.stopPropagation();
            removeIdentity(i.id);
          }}
        >
          unlink
        </Button>
      ),
    },
  ];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>account</h1>
          <div style={{ flex: 1 }} />
          <Button variant="ghost" onClick={logout}>
            sign out
          </Button>
        </div>
        <p className={styles.blurb}>
          {me ? `signed in as ${me.displayName} (#${me.id}). ` : ""}
          Связки — linked git identities; each connected repository belongs to one of them.
        </p>

        <div className={styles.list}>
          <EntityList
            columns={columns}
            rows={me?.identities ?? []}
            keyOf={(i) => String(i.id)}
            empty={meQ.loading ? "loading…" : "no identities"}
          />
        </div>

        <div className={styles.actions}>
          <Button variant="outline" onClick={() => addIdentity("github")}>
            + link GitHub
          </Button>
          <Button variant="outline" onClick={() => addIdentity("gitlab")}>
            + link GitLab
          </Button>
        </div>
      </div>
    </div>
  );
}
