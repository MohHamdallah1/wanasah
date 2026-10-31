import { defineConfig } from "vitest/config";
import base from "../vitest.config";

// Override include rather than merging arrays with the default application suite.
export default defineConfig({
  ...base,
  test: { ...base.test, include: ["e2e/live-stock-inflight-auth.test.tsx"], testTimeout: 30_000 },
});
