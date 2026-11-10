import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "dispatch-d12-scale.spec.ts",
  workers: 1, retries: 0, reporter: "list",
  outputDir: "../node_modules/.cache/dispatch-d12-scale",
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium", headless: true,
    actionTimeout: 15000, navigationTimeout: 30000,
    trace: "retain-on-failure", screenshot: "only-on-failure",
  },
});
