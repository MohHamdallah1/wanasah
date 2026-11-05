import { defineConfig } from "playwright/test";

// #782 shell-only browser acceptance. Mocked authorized HTTP, not PG16 proof.
export default defineConfig({
  testDir: ".",
  testMatch: "stocktake-v1-shell-layout.spec.ts",
  workers: 1,
  retries: 0,
  timeout: 30000,
  reporter: "list",
  outputDir: "../node_modules/.cache/stocktake-v1-shell-layout",
  use: {
    baseURL: process.env.STOCKTAKE_SHELL_BASE_URL ?? "http://127.0.0.1:4173",
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
  },
});
