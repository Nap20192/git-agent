/** Top-level nav registry. Adding a screen = one entry here + one <Route> in App.tsx. */
export interface ScreenMeta {
  num: string;
  path: string;
  id: string;
  label: string;
}

export const SCREENS: ScreenMeta[] = [
  { num: "1", path: "/runs", id: "runs", label: "runs" },
  { num: "2", path: "/reports", id: "reports", label: "reports" },
  { num: "3", path: "/connections", id: "connections", label: "connections" },
  { num: "4", path: "/sandboxes", id: "sandboxes", label: "sandboxes" },
  { num: "5", path: "/skills", id: "skills", label: "skills" },
  { num: "6", path: "/dash", id: "dash", label: "overview" },
];

export const DEFAULT_SCREEN = "/runs";
