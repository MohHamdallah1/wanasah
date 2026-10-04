import { defineConfig } from "playwright/test";

/** Isolated, intercepted Phase 2 read acceptance; no live backend or terminal commands. */
export default defineConfig({
  testDir: ".",
  testMatch: "quality-readiness.spec.ts",
  workers: 1,
  retries: 0,
  reporter: "list",
  outputDir: "../node_modules/.cache/quality-readiness-browser",
  use: {
    baseURL: process.env.QUALITY_READINESS_BASE_URL ?? "http://127.0.0.1:4173",
    browserName: "chromium",
    channel: process.env.QUALITY_READINESS_BROWSER_CHANNEL ?? "msedge",
    headless: true,
  },
});
