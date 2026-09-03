import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { ApiProvider, api } from "@/api";
import { HubApiProvider, hubApi } from "@/api/hub";
import { HubGate } from "@/features/hub/HubGate.tsx";
import { AccountScreen } from "@/features/hub/AccountScreen.tsx";
import { RepositoriesScreen } from "@/features/hub/RepositoriesScreen.tsx";
import { RepoScreen } from "@/features/hub/RepoScreen.tsx";
import { PlaygroundScreen } from "@/features/hub/PlaygroundScreen.tsx";
import { BuildsScreen } from "@/features/hub/BuildsScreen.tsx";
import { AppShell } from "@/components/layout/AppShell.tsx";
import { DEFAULT_SCREEN } from "@/app/screens.ts";
import { RunsScreen } from "@/features/runs/RunsScreen.tsx";
import { ReportsScreen } from "@/features/reports/ReportsScreen.tsx";
import { RunDetailScreen } from "@/features/runs/RunDetailScreen.tsx";
import { ReportScreen } from "@/features/runs/ReportScreen.tsx";
import { ConnectionsScreen } from "@/features/connections/ConnectionsScreen.tsx";
import { SandboxesScreen } from "@/features/sandboxes/SandboxesScreen.tsx";
import { SkillsScreen } from "@/features/skills/SkillsScreen.tsx";
import { OverviewScreen } from "@/features/overview/OverviewScreen.tsx";

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to={DEFAULT_SCREEN} replace /> },
      { path: "runs", element: <RunsScreen /> },
      { path: "reports", element: <ReportsScreen /> },
      { path: "runs/:id", element: <RunDetailScreen /> },
      { path: "runs/:id/report", element: <ReportScreen /> },
      { path: "connections", element: <ConnectionsScreen /> },
      { path: "sandboxes", element: <SandboxesScreen /> },
      { path: "skills", element: <SkillsScreen /> },
      { path: "dash", element: <OverviewScreen /> },
      {
        element: <HubGate />,
        children: [
          { path: "repos", element: <RepositoriesScreen /> },
          { path: "repos/:id", element: <RepoScreen /> },
          { path: "instances/:id", element: <PlaygroundScreen /> },
          { path: "builds", element: <BuildsScreen /> },
          { path: "account", element: <AccountScreen /> },
        ],
      },
      { path: "*", element: <Navigate to={DEFAULT_SCREEN} replace /> },
    ],
  },
]);

export function App() {
  return (
    <ApiProvider value={api}>
      <HubApiProvider value={hubApi}>
        <RouterProvider router={router} />
      </HubApiProvider>
    </ApiProvider>
  );
}
