import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  executeOpeningValuationFinalize,
  readPendingOpeningValuation,
  type OpeningValuationFinalizePayload,
} from "./openingValuation";

const payload: OpeningValuationFinalizePayload = {
  snapshot_hash: "a".repeat(64),
  lines: [{ sku: "SKU-1", unit_cost: "2.500000" }],
  confirm_zero_costs: false,
};

describe("Opening valuation durable finalize", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("keeps the exact command when a 200 response cannot be verified", async () => {
    const fetch = vi.fn().mockResolvedValue({
      message: "OPENING_VALUATION_POSTED",
    });

    await expect(
      executeOpeningValuationFinalize({
        companyId: 1,
        actorId: 2,
        payload,
        authenticatedFetch: fetch,
      }),
    ).rejects.toMatchObject({
      message: "OPENING_VALUATION_RESPONSE_INVALID",
    });

    const pending = await readPendingOpeningValuation(1, 2);
    expect(pending).not.toBeNull();
    expect(pending?.payload).toEqual(payload);
  });

  it("clears the command after a deterministic business rejection", async () => {
    const error = Object.assign(new Error("stale"), {
      code: "OPENING_VALUATION_SNAPSHOT_STALE",
      status: 409,
    });
    const fetch = vi.fn().mockRejectedValue(error);

    await expect(
      executeOpeningValuationFinalize({
        companyId: 1,
        actorId: 2,
        payload,
        authenticatedFetch: fetch,
      }),
    ).rejects.toMatchObject({
      code: "OPENING_VALUATION_SNAPSHOT_STALE",
    });

    expect(await readPendingOpeningValuation(1, 2)).toBeNull();
  });

  it("clears the command only after a strict valid success response", async () => {
    const fetch = vi.fn().mockResolvedValue({
      message: "OPENING_VALUATION_POSTED",
      method: "FIFO",
      currency_code: "JOD",
      snapshot_hash: "a".repeat(64),
      line_count: 1,
      total_quantity: "2.000000",
      total_value: "5.000000",
      zero_cost_count: 0,
      policy_version: 3,
    });

    await expect(
      executeOpeningValuationFinalize({
        companyId: 1,
        actorId: 2,
        payload,
        authenticatedFetch: fetch,
      }),
    ).resolves.toMatchObject({
      message: "OPENING_VALUATION_POSTED",
      method: "FIFO",
    });

    expect(await readPendingOpeningValuation(1, 2)).toBeNull();
  });
});
