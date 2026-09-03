import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { HubApiProvider, hubApi } from "@/api/hub";
import { HubGate } from "@/features/hub/HubGate.tsx";
import { AccountScreen } from "@/features/hub/AccountScreen.tsx";
import { RepositoriesScreen } from "@/features/hub/RepositoriesScreen.tsx";
import { RepoScreen } from "@/features/hub/RepoScreen.tsx";
import { PlaygroundScreen } from "@/features/hub/PlaygroundScreen.tsx";
import { DashScreen } from "@/features/hub/DashScreen.tsx";
import { BuildsScreen } from "@/features/hub/BuildsScreen.tsx";
import { AppShell } from "@/components/layout/AppShell.tsx";
import { DEFAULT_SCREEN } from "@/app/screens.ts";

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to={DEFAULT_SCREEN} replace /> },
      {
        element: <HubGate />,
        children: [
          { path: "dash", element: <DashScreen /> },
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
    <HubApiProvider value={hubApi}>
      <RouterProvider router={router} />
    </HubApiProvider>
  );
}
