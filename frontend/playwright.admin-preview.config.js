import { defineConfig } from "@playwright/test";
import base from "./playwright.config.js";

export default defineConfig({
  ...base,
  testDir: "./preview",
  use: { ...base.use, baseURL: "http://127.0.0.1:5194" },
  webServer: {
    command: "npm run dev:admin-preview -- --port 5194",
    url: "http://127.0.0.1:5194",
    reuseExistingServer: !process.env.CI,
    env: { VITE_API_BASE_URL: "/api/v1" },
  },
});
