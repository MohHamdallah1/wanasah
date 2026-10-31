import { defineConfig } from "playwright/test";
import operational from "./live-stock-operational.config";
export default defineConfig({
  ...operational,
  testMatch: "live-stock-physical-custody.spec.ts",
  outputDir: "../node_modules/.cache/live-stock-physical-custody",
});
