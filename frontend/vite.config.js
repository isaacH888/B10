import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  // The browser must send its session cookie to the same origin as the app.
  if (env.VITE_API_BASE_URL && env.VITE_API_BASE_URL !== "/api/v1") {
    throw new Error("VITE_API_BASE_URL must be /api/v1. Proxy API traffic on the website origin.");
  }
  const proxy = {
    "/api/v1": { target: "http://127.0.0.1:5000", changeOrigin: false },
  };
  return {
    plugins: [react()],
    server: { host: "localhost", port: 5173, strictPort: true, proxy },
    preview: { host: "localhost", port: 4173, strictPort: true, proxy },
  };
});
