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
    // Proxy API calls to the git-agent backend during dev. Toggle the mock
    // adapter in src/api instead if the backend isn't running (see docs/API_CONTRACT.md).
    proxy: {
      "/api": { target: "http://localhost:8080", changeOrigin: true },
    },
  },
});
