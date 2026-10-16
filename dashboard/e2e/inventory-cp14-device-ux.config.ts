import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "inventory-cp14-device-ux.spec.ts",
  workers: 1,
  retries: 0,
  reporter: "list",
  outputDir: "../node_modules/.cache/inventory-cp14-device-ux",
  use: {
    baseURL: process.env.CP14D_BASE_URL ?? "http://127.0.0.1:4173",
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
  },
});
