import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,

    proxy: {
      // Go hub (backend/cmd/hub, HUB_ADDR, default :8081). The hub api layer
      // prefixes its requests with VITE_HUB_URL=/hub; strip it here so the
      // session cookie stays same-origin.
      "/hub": {
        target: "http://localhost:8081",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/hub/, ""),
      },
    },
  },
});
