import { defineConfig } from "playwright/test";
export default defineConfig({
  testDir: ".", testMatch: "ledger-762.spec.ts",
  workers: 1, retries: 0, reporter: "list",
  outputDir: "../node_modules/.cache/ledger-762",
  use: { baseURL: "http://127.0.0.1:4173", browserName: "chromium",
    headless: true, trace: "retain-on-failure" },
});
