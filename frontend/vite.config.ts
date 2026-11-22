import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

// HTTPS=1 enables a self-signed certificate so phone browsers allow camera access.
const https = process.env.HTTPS === "1";
const backend = process.env.HCCB_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), ...(https ? [basicSsl()] : [])],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/r/": { target: backend, changeOrigin: true },
    },
  },
  test: { environment: "node" },
});
