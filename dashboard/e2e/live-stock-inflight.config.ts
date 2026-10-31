import { defineConfig, mergeConfig } from "vitest/config";
import base from "../vitest.config";

export default mergeConfig(base, defineConfig({
  test: { include: ["e2e/live-stock-inflight-auth.test.tsx"], testTimeout: 30_000 },
}));
