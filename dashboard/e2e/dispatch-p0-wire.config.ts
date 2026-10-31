import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "dispatch-p0-wire.spec.ts",
  workers: 1, retries: 0, reporter: "list",
  outputDir: "../node_modules/.cache/dispatch-p0-wire",
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    headless: true, actionTimeout: 15_000, navigationTimeout: 30_000,
    trace: "retain-on-failure", screenshot: "only-on-failure",
  },
});
