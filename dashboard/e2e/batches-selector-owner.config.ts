import { defineConfig } from "playwright/test";
export default defineConfig({
  testDir: ".", testMatch: "batches-selector-owner.spec.ts",
  workers: 1, retries: 0, reporter: "list",
  outputDir: "../node_modules/.cache/batches-selector-owner",
  use: { baseURL: "http://127.0.0.1:4173", browserName: "chromium",
    headless: true, trace: "retain-on-failure" },
});
