import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

export default defineConfig(async ({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  // The browser must send its session cookie to the same origin as the app.
  if (env.VITE_API_BASE_URL && env.VITE_API_BASE_URL !== "/api/v1") {
    throw new Error(
      "VITE_API_BASE_URL must be /api/v1. Proxy API traffic on the website origin.",
    );
  }
  const proxy = {
    "/api/v1": { target: "http://127.0.0.1:5000", changeOrigin: false },
  };
  const { stdout: commit } = await promisify(execFile)(
    "git",
    ["rev-parse", "HEAD"],
    {
      cwd: fileURLToPath(new URL("..", import.meta.url)),
    },
  );
  return {
    define: {
      __SITE_COMMIT__: JSON.stringify(commit.trim()),
    },
    plugins: [react()],
    server: { host: "localhost", port: 5173, strictPort: true, proxy },
    preview: { host: "localhost", port: 4173, strictPort: true, proxy },
  };
});
