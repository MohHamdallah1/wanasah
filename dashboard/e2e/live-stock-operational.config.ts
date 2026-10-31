import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "live-stock-operational.spec.ts",
  workers: 1,
  retries: 0,
  reporter: "list",
  outputDir: "../node_modules/.cache/live-stock-operational",
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    headless: true,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    timezoneId: "Pacific/Honolulu",
    trace: "off",
    screenshot: "only-on-failure",
  },
});
