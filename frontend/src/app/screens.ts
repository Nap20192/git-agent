/** Top-level nav registry. Adding a screen = one entry here + one <Route> in App.tsx. */
export interface ScreenMeta {
  num: string;
  path: string;
  id: string;
  label: string;
}

// hub (Go backend) — repo pages own their agent (Экземпляр), see src/api/hub
export const SCREENS: ScreenMeta[] = [
  { num: "1", path: "/repos", id: "repos", label: "repos" },
  { num: "2", path: "/builds", id: "builds", label: "builds" },
  { num: "3", path: "/account", id: "account", label: "account" },
];

export const DEFAULT_SCREEN = "/repos";
