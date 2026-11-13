import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { adminPreviewPlugin } from "./preview/adminPreviewPlugin.js";

export default defineConfig(({ command, mode }) => {
  if (command !== "serve" || mode !== "admin-preview") {
    throw new Error(
      "Use npm run dev:admin-preview for the local sample preview.",
    );
  }
  return {
    plugins: [react(), adminPreviewPlugin()],
    server: {
      host: "127.0.0.1",
      port: 5174,
      strictPort: true,
      // Every API request is handled by the sample middleware. No backend proxy.
      proxy: {},
    },
  };
});
