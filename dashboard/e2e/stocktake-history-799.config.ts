import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "stocktake-history-799.spec.ts",
  workers: 1,
  retries: 0,
  timeout: 30000,
  reporter: "list",
  outputDir: "../node_modules/.cache/stocktake-history-799",
  use: {
    baseURL: process.env.STOCKTAKE_799_BASE_URL ?? "http://127.0.0.1:4173",
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
  },
});
