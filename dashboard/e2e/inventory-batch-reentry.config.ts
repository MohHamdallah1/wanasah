import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "inventory-batch-reentry.spec.ts",
  workers: 1,
  retries: 0,
  reporter: "list",
  outputDir: "../node_modules/.cache/inventory-batch-reentry",
  use: {
    baseURL: process.env.IT03_BASE_URL ?? "http://127.0.0.1:4173",
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
  },
});
