/** Top-level nav registry. Adding a screen = one entry here + one <Route> in App.tsx. */
export interface ScreenMeta {
  num: string;
  path: string;
  id: string;
  label: string;
}

export const SCREENS: ScreenMeta[] = [
  { num: "1", path: "/runs", id: "runs", label: "runs" },
  { num: "2", path: "/connections", id: "connections", label: "connections" },
  { num: "3", path: "/sandboxes", id: "sandboxes", label: "sandboxes" },
  { num: "4", path: "/skills", id: "skills", label: "skills" },
  { num: "5", path: "/dash", id: "dash", label: "overview" },
];

export const DEFAULT_SCREEN = "/runs";
