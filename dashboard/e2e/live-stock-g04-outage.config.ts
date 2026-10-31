import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "live-stock-g04-outage.spec.ts",
  workers: 1,
  retries: 0,
  reporter: [["list"], ["junit", { outputFile: "../node_modules/.cache/live-stock-g04-outage.xml" }]],
  outputDir: "../node_modules/.cache/live-stock-g04-outage",
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    headless: true,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
