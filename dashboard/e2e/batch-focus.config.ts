import { defineConfig } from "playwright/test";

/** Opt-in, read-only acceptance against a separately started local preview. */
export default defineConfig({
  testDir: ".",
  testMatch: "batch-focus.spec.ts",
  workers: 1,
  retries: 0,
  reporter: "list",
  outputDir: "../node_modules/.cache/batch-focus-browser",
  use: {
    baseURL: process.env.BATCH_FOCUS_BASE_URL ?? "http://127.0.0.1:4173",
    browserName: "chromium",
    channel: process.env.BATCH_FOCUS_BROWSER_CHANNEL ?? "msedge",
    headless: true,
  },
});
